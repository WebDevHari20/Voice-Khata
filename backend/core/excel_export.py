from io import BytesIO
from math import isfinite
from xml.sax.saxutils import escape
from zipfile import ZIP_DEFLATED, ZipFile


def _clean_text(value):
    text = str(value if value is not None else "")
    return "".join(char for char in text if char in "\t\n\r" or ord(char) >= 32)


def _column_name(index):
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


def _cell(reference, value):
    if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(float(value)):
        return f'<c r="{reference}"><v>{value}</v></c>'
    text = escape(_clean_text(value))
    return f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'


def _worksheet(rows):
    row_xml = []
    for row_index, row in enumerate(rows, 1):
        cells = "".join(_cell(f"{_column_name(col_index)}{row_index}", value)
                         for col_index, value in enumerate(row, 1))
        row_xml.append(f'<row r="{row_index}">{cells}</row>')
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            f'<sheetData>{"".join(row_xml)}</sheetData></worksheet>')


def build_workbook(balances, events):
    balance_rows = [["Customer", "Balance status", "Total amount (INR)"]]
    balance_rows.extend([
        [row["customer"], "Owes you" if row["net_due"] >= 0 else "You owe", abs(row["net_due"])]
        for row in balances
    ])
    event_rows = [["Event ID", "Date", "Customer", "Event", "Amount (INR)", "Status", "Corrects", "Confidence", "Details", "Created at"]]
    for event in events:
        kind = event.get("type", "")
        signed_amount = event.get("amount")
        if isinstance(signed_amount, (int, float)) and kind == "payment":
            signed_amount = -signed_amount
        event_rows.append([
            event.get("event_id"), event.get("date"), event.get("customer_name"), kind,
            signed_amount, event.get("status"), event.get("corrects"), event.get("confidence"),
            event.get("meta"), event.get("created_at"),
        ])

    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
</Types>''')
        archive.writestr("_rels/.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''')
        archive.writestr("xl/workbook.xml", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="Balances" sheetId="1" r:id="rId1"/><sheet name="Event History" sheetId="2" r:id="rId2"/></sheets>
</workbook>''')
        archive.writestr("xl/_rels/workbook.xml.rels", '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet2.xml"/>
</Relationships>''')
        archive.writestr("xl/worksheets/sheet1.xml", _worksheet(balance_rows))
        archive.writestr("xl/worksheets/sheet2.xml", _worksheet(event_rows))
    return buffer.getvalue()
