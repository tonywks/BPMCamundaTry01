from pathlib import Path
from xml.etree import ElementTree as ET


BPMN = "http://www.omg.org/spec/BPMN/20100524/MODEL"
BPMNDI = "http://www.omg.org/spec/BPMN/20100524/DI"


def test_purchase_bpmn_contains_modeler_renderable_diagram():
    path = Path(__file__).parent.parent / "processes" / "purchase-approval.bpmn"
    root = ET.parse(path).getroot()
    diagram = root.find(f"{{{BPMNDI}}}BPMNDiagram")
    assert diagram is not None, "Camunda Modeler needs BPMN-DI diagram metadata to render the process"
    plane = diagram.find(f"{{{BPMNDI}}}BPMNPlane")
    assert plane is not None
    assert plane.get("bpmnElement") == "purchase-approval"
    shape_elements = {shape.get("bpmnElement") for shape in plane.findall(f"{{{BPMNDI}}}BPMNShape")}
    assert {"start", "route", "manager_approval", "end"}.issubset(shape_elements)
