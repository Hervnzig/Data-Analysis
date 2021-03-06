import pandas as pd
import numpy as np

from tqdm import tqdm_notebook


def cyclical_encoding(series, period):
    features = pd.concat([np.sin((2 * np.pi * series / period)),
                          np.cos((2 * np.pi * series / period))], axis=1)
    features.columns = [f'sin_{series.name}', f'cos_{series.name}']
    return features


def create_time_features(
    fld, keep_frac_only=False, include_additional=False, cyc_encode=False, timezone=None,
):
    """
    Create features out of a series of datetimes.
    Time zones are converted to local time if specified.

    :param fld: series of datetimes
    :param keep_frac_only: maintain only fractional times
    :param include_additional: whether to include additional attributes
    :param cyc_encode: whether to cyclically encode time and date features
    :param timezone: string for the time zone. if passed, times are converted to local

    :return df: dataframe with added date and time columns
    """
    # Convert to a series (in case of index)
    fld = pd.to_datetime(pd.Series(fld))

    # Create a dataframe with index as original times
    df = fld.to_frame().drop(columns=[fld.name])

    # Used for naming the columns
    prefix = fld.name
    prefix += "_"

    # Convert to local time and then remove time zone information
    if timezone:
        fld = fld.dt.tz_convert(timezone).dt.tz_localize(None)
        df["local"] = fld

    # Basic attributes
    attr = ["year", "month", "week", "day", "dayofweek", "dayofyear"]

    if include_additional:
        # Additional attributes to extract
        attr = attr + [
            "is_month_end",
            "is_month_start",
            "is_quarter_end",
            "is_quarter_start",
            "is_year_end",
            "is_year_start",
            "days_in_month",
        ]

    # Time attributes
    attr = attr + ["hour", "minute", "second"]

    # iterate through each attribute and add it to the dataframe
    for n in attr:
        df[prefix + n] = getattr(fld.dt, n)

    # Add fractional time of day converting to hours
    df[prefix + "fracday"] = (
        df[prefix + "hour"]
        + df[prefix + "minute"] / 60
        + df[prefix + "second"] / 60 / 60
    ) / 24

    # Add fractional time of week converting to hours
    df[prefix + "fracweek"] = (
        (df[prefix + "dayofweek"] * 24) + (df[prefix + "fracday"] * 24)
    ) / (7 * 24)

    # Add fractional time of month converting to hours
    df[prefix + "fracmonth"] = (
        (df[prefix + "day"] - 1) * 24 + df[prefix + "fracday"] * 24
    ) / (
        fld.dt.days_in_month * 24
    )  # Use fld days_in_month in case this is not
    # one of the attributes specified

    # Calculate days in year
    days_in_year = np.where(
        (df[prefix + "year"] % 4 == 0)
        & ((df[prefix + "year"] % 100 != 0) | (df[prefix + "year"] % 400 == 0)),
        366,
        365,
    )

    # Add fractional time of year converting to hours
    df[prefix + "fracyear"] = (
        (df[prefix + "dayofyear"] - 1) * 24 + df[prefix + "fracday"] * 24
    ) / (days_in_year * 24)

    if cyc_encode:
        df = pd.concat([df, cyclical_encoding(
            df[prefix + 'hour'], 23)], axis=1)
        df = pd.concat([df, cyclical_encoding(
            df[prefix + 'dayofweek'], 6)], axis=1)
        df = pd.concat([df, cyclical_encoding(df[prefix + 'day'], 30)], axis=1)
        df = pd.concat([df, cyclical_encoding(
            df[prefix + 'month'], 12)], axis=1)
        df = pd.concat([df] + [cyclical_encoding(df[c], 1)
                               for c in df if 'frac' in c], axis=1)

    if keep_frac_only:
        df = df.drop(
            [
                prefix + c
                for c in [
                    "second",
                    "minute",
                    "hour",
                    "year",
                    "month",
                    "week",
                    "day",
                    "dayofweek",
                    "dayofyear",
                ]
            ],
            axis=1,
        )

    df = df.set_index(fld).sort_index()

    return df


def monthly_validation(data, model, track=False):
    train_stops = np.unique(data.index[data.index.is_month_end].date)

    X = data.copy()
    y = X.pop('energy')
    weighted_score = 0
    total_possible = 0
    train_points = []
    test_points = []
    scores = []

    for date in train_stops:
        y_train, y_test = y[:date], y[date:]
        X_train, X_test = X[:date], X[date:]

        model.fit(X_train, y_train)
        y_hat = model.predict(X_test)

        test_start, test_end = X_test.index.min().date(), X_test.index.max().date()
        n_days = (test_end - test_start).days
        score = 100 - mape(y_test, y_hat)

        if track:
            print(
                f'Accuracy: {score:.2f}% testing from {test_start} to {test_end} ({n_days} days).')
        weighted_score += score * len(X_test)
        total_possible += 100 * len(X_test)
        train_points.append(len(X_train))
        test_points.append(len(X_test))
        scores.append(score)

    model.fit(X, y)

    importance_df = None
    if hasattr(model, 'feature_importances_'):
        importance_df = pd.DataFrame(
            dict(features=X.columns, importance=model.feature_importances_))
    final_score = weighted_score / total_possible
    results_df = pd.DataFrame(
        dict(train_points=train_points, test_points=test_points, score=scores))
    return dict(results=results_df, importances=importance_df, score=final_score)


def mape(y_true, y_pred):
    return 100 * np.mean(np.abs((y_pred - y_true) / y_true))
