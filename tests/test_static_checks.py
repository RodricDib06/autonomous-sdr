"""
Static checks for bug classes that only fail at runtime, on a line that is
usually wrapped in try/except — so they fail silently:

  - stdlib loggers called with structlog-style key=value kwargs (TypeError at
    the log line): silently broke ML training, Bayesian re-qualification and
    web enrichment
  - lazy `from app.x import y` inside functions where y doesn't exist: the
    reply-score boost imported a function from the wrong module for months
"""
import ast
import importlib
import pathlib

_STDLIB_KWARGS = {"exc_info", "stack_info", "stacklevel", "extra"}
_LEVELS = {"debug", "info", "warning", "error", "exception", "critical"}


def _stdlib_logger_names(tree: ast.AST) -> set[str]:
    names = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)
                and ast.unparse(node.value.func) == "logging.getLogger"):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
    return names


def test_no_structlog_kwargs_on_stdlib_loggers():
    offenders = []
    for path in sorted(pathlib.Path("app").rglob("*.py")):
        tree = ast.parse(path.read_text())
        loggers = _stdlib_logger_names(tree)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in loggers and node.func.attr in _LEVELS):
                bad = [k.arg for k in node.keywords if k.arg not in _STDLIB_KWARGS]
                if bad:
                    offenders.append(f"{path}:{node.lineno} {', '.join(bad)}")
    assert not offenders, "stdlib logger called with structlog kwargs:\n" + "\n".join(offenders)


def test_every_app_import_resolves():
    offenders = []
    for path in sorted([*pathlib.Path("app").rglob("*.py"), *pathlib.Path("scripts").glob("*.py")]):
        for node in ast.walk(ast.parse(path.read_text())):
            if not (isinstance(node, ast.ImportFrom) and node.level == 0
                    and (node.module or "").startswith("app")):
                continue
            module = importlib.import_module(node.module)
            for alias in node.names:
                if alias.name == "*" or hasattr(module, alias.name):
                    continue
                try:
                    importlib.import_module(f"{node.module}.{alias.name}")
                except ImportError:
                    offenders.append(f"{path}:{node.lineno} {node.module} has no {alias.name}")
    assert not offenders, "unresolvable imports:\n" + "\n".join(offenders)


def test_bayesian_update_does_not_raise(test_db):
    from app.database.models import Lead, Verdict
    from app.services.bayesian_updater import apply_bayesian_update

    lead = Lead(name="L", email="l@x.com", company="C")
    test_db.add(lead)
    test_db.commit()
    test_db.add(Verdict(lead_id=lead.id, final_verdict="Warm", confidence_score=0.5,
                        bant_scores={"budget": 0.5, "authority": 0.5, "need": 0.5, "timeline": 0.5}))
    test_db.commit()

    result = apply_bayesian_update(test_db, lead.id, "click")
    assert result and result["new_confidence"] > 0.5
