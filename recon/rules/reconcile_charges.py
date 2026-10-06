"""Правила сверки начислений за месяц: наличие записей, суммы, счёт, общие итоги."""

from recon.rules import Discrepancy, ReconContext, reconcile_rule


@reconcile_rule("missing_in_target", "начисление есть в 1С, но нет в PostgreSQL")
def missing_in_target(ctx: ReconContext):
    for record_id in sorted(ctx.source.keys() - ctx.target.keys()):
        yield Discrepancy(
            "missing_in_target",
            record_id,
            ctx.source[record_id].as_dict(),
            None,
            "нет в PostgreSQL",
        )


@reconcile_rule("missing_in_source", "начисление есть в PostgreSQL, но нет в 1С")
def missing_in_source(ctx: ReconContext):
    for record_id in sorted(ctx.target.keys() - ctx.source.keys()):
        yield Discrepancy(
            "missing_in_source", record_id, None, ctx.target[record_id].as_dict(), "нет в 1С"
        )


@reconcile_rule("amount_mismatch", "у одного начисления разные суммы")
def amount_mismatch(ctx: ReconContext):
    for record_id in sorted(ctx.source.keys() & ctx.target.keys()):
        source, target = ctx.source[record_id], ctx.target[record_id]
        if source.amount_kopecks != target.amount_kopecks:
            diff = target.amount_kopecks - source.amount_kopecks
            yield Discrepancy(
                "amount_mismatch",
                record_id,
                source.as_dict(),
                target.as_dict(),
                f"разница {diff:+d} коп. (PostgreSQL − 1С)",
            )


@reconcile_rule("account_mismatch", "у одного начисления разные лицевые счета")
def account_mismatch(ctx: ReconContext):
    for record_id in sorted(ctx.source.keys() & ctx.target.keys()):
        source, target = ctx.source[record_id], ctx.target[record_id]
        if source.account_id != target.account_id:
            yield Discrepancy(
                "account_mismatch",
                record_id,
                source.as_dict(),
                target.as_dict(),
                f"счёт {source.account_id} в 1С, {target.account_id} в PostgreSQL",
            )


@reconcile_rule("totals_mismatch", "количество и сумма начислений за месяц совпадают")
def totals_mismatch(ctx: ReconContext):
    source = {"count": len(ctx.source), "amount_kopecks": _total(ctx.source)}
    target = {"count": len(ctx.target), "amount_kopecks": _total(ctx.target)}
    if source != target:
        yield Discrepancy(
            "totals_mismatch", None, source, target, f"итоги за {ctx.period} не совпадают"
        )


def _total(charges) -> int:
    return sum(charge.amount_kopecks for charge in charges.values())
