from copy import deepcopy
from typing import TYPE_CHECKING

from .blocking import _sql_gen_where_condition, block_using_rules_sql
from .settings import Settings
from .comparison_library import exact_match
from .misc import calculate_cartesian, calculate_reduction_ratio
from .vertically_concatenate import vertically_concatenate_sql

# https://stackoverflow.com/questions/39740632/python-type-hinting-without-cyclic-imports
if TYPE_CHECKING:
    from .linker import Linker


def get_link_type_settings_obj(
    linker: "Linker",
    link_type=None,
    unique_id_column_name=None,
):

    if linker._settings_obj_ is not None:
        settings_obj = linker._settings_obj

    if link_type is None and linker._settings_obj_ is None:
        if len(linker._input_tables_dict.values()) == 1:
            link_type = "dedupe_only"

    if link_type is not None:
        # Minimal settings dict
        if unique_id_column_name is None:
            raise ValueError(
                "If settings not provided, you must specify unique_id_column_name"
            )
        settings_obj = Settings(
            {
                "unique_id_column_name": unique_id_column_name,
                "link_type": link_type,
                "comparisons": [exact_match("first_name")],
            }
        )

    # If link type not specified or inferrable, raise error
    if link_type is None:
        if linker._settings_obj_ is None:
            raise ValueError(
                "Must provide a link_type argument to analyse_blocking_rule_sql "
                "if linker has no settings object"
            )

    return settings_obj


def number_of_comparisons_generated_by_blocking_rule_sql(
    linker: "Linker", blocking_rule, link_type=None, unique_id_column_name=None
) -> str:

    settings_obj = get_link_type_settings_obj(
        linker,
        link_type,
        unique_id_column_name,
    )

    where_condition = _sql_gen_where_condition(
        settings_obj._link_type, settings_obj._unique_id_input_columns
    )

    sql = f"""
    select count(*) as count_of_pairwise_comparisons_generated

    from __splink__df_concat as l
    inner join __splink__df_concat as r
    on
    {blocking_rule}
    {where_condition}
    """

    return sql


def cumulative_comparisons_generated_by_blocking_rules(
    linker: "Linker",
    blocking_rules,
    link_type=None,
    unique_id_column_name=None,
):

    settings_obj = get_link_type_settings_obj(
        linker=linker,
        link_type=link_type,
        unique_id_column_name=unique_id_column_name,
    )
    linker._settings_obj_ = settings_obj
    # Deepcopy our original linker so we can safely adjust our settings.
    # This is particularly important to ensure we don't overwrite our
    # original blocking rules.
    copied_linker = deepcopy(linker)
    if blocking_rules:
        brs_as_objs = settings_obj._brs_as_objs(blocking_rules)
        copied_linker._settings_obj_._blocking_rules_to_generate_predictions = (
            brs_as_objs
        )

    # Calculate the Cartesian Product
    if len(linker._input_tables_dict) == 1:
        group_by_statement = ""
    else:
        group_by_statement = "group by source_dataset"

    sql = vertically_concatenate_sql(linker)
    linker._enqueue_sql(sql, "__splink__df_concat")

    sql = f"""
        select count(*) as count
        from __splink__df_concat
        {group_by_statement}
    """
    linker._enqueue_sql(sql, "__splink__cartesian_product")
    cartesian_count = linker._execute_sql_pipeline()
    row_count_df = cartesian_count.as_record_dict()
    cartesian_count.drop_table_from_database()

    cartesian = calculate_cartesian(row_count_df, settings_obj._link_type)

    # Calculate the total number of rows generated by each blocking rule
    linker._initialise_df_concat_with_tf(materialise=False)
    sql = block_using_rules_sql(copied_linker)
    linker._enqueue_sql(sql, "__splink__df_blocked_data")

    brs_as_objs = copied_linker._settings_obj_._blocking_rules_to_generate_predictions
    group_by = "group by match_key" if len(brs_as_objs) > 1 else ""

    sql = f"""
        select count(*) as row_count
        from __splink__df_blocked_data
        {group_by}
    """
    linker._enqueue_sql(sql, "__splink__df_count_cumulative_blocks")
    cumulative_blocking_rule_count = linker._execute_sql_pipeline()
    br_count = cumulative_blocking_rule_count.as_record_dict()
    cumulative_blocking_rule_count.drop_table_from_database()

    br_comparisons = []
    cumulative_sum = 0
    # Wrap everything into an output dictionary
    for row, br in zip(br_count, brs_as_objs):

        cumulative_sum += row["row_count"]
        rr = round(calculate_reduction_ratio(cumulative_sum, cartesian), 3)

        rr_text = (
            f"The rolling reduction ratio with your given blocking rule(s) is {rr}. "
            "\nThis represents the reduction in the total number of comparisons due "
            "to your rule(s)."
        )

        out_dict = {
            "row_count": row["row_count"],
            "rule": br.blocking_rule,
            "cumulative_rows": cumulative_sum,
            "cartesian": int(cartesian),
            "reduction_ratio": rr_text,
            "start": cumulative_sum - row["row_count"],
        }
        br_comparisons.append(out_dict.copy())

    return br_comparisons
