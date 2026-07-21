import xmltodict


def parse_credit_xml(xml_response: str) -> dict:
    """
    Converts the MISMO XML credit report response
    into a Python dictionary.

    Args:
        xml_response: Raw XML response from the credit API.

    Returns:
        Parsed XML as a Python dictionary.
    """

    if not xml_response or not xml_response.strip():
        raise ValueError("Credit report XML response is empty")

    try:
        parsed_data = xmltodict.parse(
            xml_response,
            process_namespaces=False
        )

        return parsed_data

    except Exception as e:
        raise ValueError(
            f"Failed to parse credit report XML: {str(e)}"
        )