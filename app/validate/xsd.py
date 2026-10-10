"""M8: проверка XML по официальным XSD BPMN 2.0."""
from pathlib import Path
from lxml import etree

_DIR = Path(__file__).parent / "xsd"
_schema = None


def validate_xsd(xml: str) -> dict:
    global _schema
    try:
        if _schema is None:
            _schema = etree.XMLSchema(etree.parse(str(_DIR / "BPMN20.xsd")))
        doc = etree.fromstring(xml.encode("utf-8"))
    except etree.XMLSyntaxError as e:
        return {"valid": False, "errors": [{"line": e.lineno or 0, "message": str(e)}]}
    except (OSError, etree.XMLSchemaParseError) as e:
        return {"valid": None, "errors": [{"line": 0, "message": f"XSD недоступна: {e}"}]}
    ok = _schema.validate(doc)
    return {"valid": bool(ok), "errors": [{"line": x.line, "message": x.message} for x in _schema.error_log]}
