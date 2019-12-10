import logging

from .logging_utils import log_sql, format_sql
from .sql import comparison_columns_select_expr, sql_gen_comparison_columns

log = logging.getLogger(__name__)


def sql_gen_block_using_rules(columns_to_retain: list, blocking_rules: list, unique_id_col: str="unique_id", table_name: str="df"):
    """Build a SQL statement that implements a list of blocking rules.

    The left and right tables are aliased as `l` and `r` respectively, so an example
    blocking rule would be `l.surname = r.surname AND l.forename = r.forename`.

    Args:
        columns_to_retain: List of columns to keep in returned dataset
        blocking_rules: Each element of the list represents a blocking rule
        unique_id_col (str, optional): The name of the column containing the row's unique_id. Defaults to "unique_id".
        table_name (str, optional): Name of the table. Defaults to "df".

    Returns:
        str: A SQL statement that implements the blocking rules
    """

    if unique_id_col not in columns_to_retain:
        columns_to_retain.insert(0, unique_id_col)

    sql_select_expr = sql_gen_comparison_columns(columns_to_retain)

    sqls = []
    for rule in blocking_rules:
        sql = f"""
        select
        {sql_select_expr}
        from {table_name} as l
        left join {table_name} as r
        on
        {rule}
        where l.{unique_id_col} < r.{unique_id_col}
        """
        sqls.append(sql)

    # Note the 'union' function in pyspark > 2.0 is not the same thing as union in a sql statement
    sql = "union all".join(sqls)

    return sql


def block_using_rules(df, columns_to_retain, blocking_rules, spark=None, unique_id_col="unique_id", logger = log):
    """Apply a series of blocking rules to create a dataframe of record comparisons.
    """

    sql = sql_gen_block_using_rules(columns_to_retain, blocking_rules, unique_id_col)

    log_sql(sql, logger)
    df.registerTempTable('df')
    df_comparison = spark.sql(sql)

    # Think this may be more efficient than using union to join each dataset because we only dropduplicates once
    df_comparison = df_comparison.dropDuplicates()

    return df_comparison


def cartestian_block(df, spark=None,  unique_id_col="unique_id"):
    columns = list(df.columns)

    sql_select_expr = comparison_columns_select_expr(df)
    df.createOrReplaceTempView("df")

    sql = f"""
    select
    {sql_select_expr}
    from df as l
    cross join df as r
    where l.{unique_id_col} < r.{unique_id_col}
    """


    # Note the 'union' function in pyspark > 2.0 is not the same thing as union in a sql statement
    df_comparison = spark.sql(sql)
    log.debug(format_sql(sql))

    return df_comparison
