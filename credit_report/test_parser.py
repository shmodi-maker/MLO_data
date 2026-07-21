from credit_report.credit_parser import parse_credit_xml
import json


with open(
    "credit_report/response.xml",
    "r",
    encoding="utf-8"
) as file:
    xml_response = file.read()


parsed_data = parse_credit_xml(xml_response)


with open(
    "credit_report/parsed_credit_response.json",
    "w",
    encoding="utf-8"
) as file:
    json.dump(
        parsed_data,
        file,
        indent=4
    )

print("Parsed response saved successfully!")