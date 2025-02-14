def unlinkables_data(linker, x_col="match_weight"):
    """Generate data displaying the proportion of records that are "unlinkable"
    for a given splink score threshold and model parameters. These are records that,
    even when compared with themselves, do not contain enough information to confirm
    a match.

    Args:
        linker (Splink): A Splink data linker
        x_col (str, optional): The column name to use as the x-axis in the chart.
            This can be either the "match_weight" or "match_probability" columns.
            Defaults to "match_weight".
        source_dataset (str, optional): Name of the source dataset (used in chart
            title). Defaults to None.
    """

    self_link = linker._self_link()

    if x_col not in ["match_weight", "match_probability"]:
        raise ValueError(
            f"{x_col} must be 'match_weight' (default) or 'match_probability'."
        )

    sql = f"""
        select
        round(match_weight, 2) as match_weight,
        round(match_probability, 5) as match_probability
        from {self_link.physical_name}
    """

    linker._enqueue_sql(sql, "__splink__df_round_self_link")

    sql = """
        select
        max(match_weight) as match_weight,
        match_probability,
        count(*) / cast( sum(count(*)) over () as float) as prop
        from __splink__df_round_self_link
        group by match_probability
        order by match_probability
    """

    linker._enqueue_sql(sql, "__splink__df_unlinkables_proportions")

    sql = """
        select *,
        sum(prop) over(order by match_probability) as cum_prop
        from __splink__df_unlinkables_proportions
        where match_probability < 1
    """
    linker._enqueue_sql(sql, "__splink__df_unlinkables_proportions_cumulative")
    data = linker._execute_sql_pipeline(materialise_as_hash=False, use_cache=False)

    unlinkables_dict = data.as_record_dict()

    return unlinkables_dict
