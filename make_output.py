"""Builds the formatted Excel output table (the deliverable the brief asks for).
Run:  python make_output.py        (writes output/Razorpay_P3_Output.xlsx)
The app's Download button uses the same code."""
import io
import os

import pandas as pd
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

import agent as ag

FONT = 'Arial'
HEAD = PatternFill('solid', start_color='1A56DB')
FILL = {'GREEN': 'DCFCE7', 'AMBER': 'FEF3C7', 'RED': 'FEE2E2'}
LABEL = {'GREEN': 'Automatic', 'AMBER': 'Check first', 'RED': 'Person handles'}
THIN = Side(style='thin', color='D1D5DB')
WIDTH = {'Priority rank': 9, 'Application': 12, 'Light': 15, 'Diagnosed cause': 38, 'Evidence': 26, 'AI second opinion': 30, 'Fixable': 14,
         'Recoverable': 13, 'Decision': 40, 'Action': 42, 'Owner': 24, 'Call slot': 18, 'Lane': 22, 'Send status': 30, 'Why it waits': 40,
         'Language': 11, 'Channel': 11, 'Email subject (Day 0)': 34, 'Email subject (Day 3)': 34, 'Email subject (Day 7)': 34,
         'Day 0 message': 70, 'Day 3 follow-up': 55, 'Day 7 follow-up': 55, 'English meaning': 70, 'Guardrail check': 16, 'Data flag': 30}


def _style_header(ws, ncols, row=1):
    for c in range(1, ncols + 1):
        cell = ws.cell(row=row, column=c)
        cell.font = Font(name=FONT, bold=True, color='FFFFFF', size=10)
        cell.fill = HEAD
        cell.alignment = Alignment(wrap_text=True, vertical='center')
    ws.row_dimensions[row].height = 30


def excel_bytes(P, S):
    T = ag.output_table(P).copy()
    lights = T['Light'].tolist()
    T['Light'] = T['Light'].map(LABEL)
    by = pd.DataFrame(S['by_code'])
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as xw:
        # Summary sheet
        summ = pd.DataFrame([
            ['Applications read', S['total']], ['Already activated (left out)', S['excluded']], ['In scope (stalled or rejected)', S['in_scope']],
            ['Recoverable', S['recoverable']], ['Expected payments at stake (Rs lakh a month)', S['recoverable_tpv']],
            ['Closed politely after a person approves', S['closures']], ['Routed to Compliance', S['holds']],
            ['Automatic', S['lights'].get('GREEN', 0)], ['Check first', S['lights'].get('AMBER', 0)], ['Person handles', S['lights'].get('RED', 0)],
            ['Sent by WhatsApp (opted in)', S['whatsapp']], ['Sent by email (not opted in)', S['email']],
            ['Messages blocked by the safety checker', S['guardrail_fail']], ['Output check code', ag.output_hash(P)]],
            columns=['Measure', 'Value'])
        summ.to_excel(xw, sheet_name='Summary', index=False)
        # Causes sheet (fixable causes, merchants and payments)
        c = by.rename(columns={'code': 'Code', 'n': 'Merchants', 'tpv': 'Payments (Rs lakh a month)'})
        c.sort_values('Merchants', ascending=False).to_excel(xw, sheet_name='Causes', index=False)
        T.to_excel(xw, sheet_name='Output', index=False)

        ws = xw.sheets['Summary']
        _style_header(ws, 2)
        ws.column_dimensions['A'].width = 48
        ws.column_dimensions['B'].width = 16
        for row in ws.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name=FONT, size=10)
                cell.border = Border(bottom=THIN)
        ws2 = xw.sheets['Causes']
        _style_header(ws2, 3)
        for col, w in zip('ABC', (10, 12, 28)):
            ws2.column_dimensions[col].width = w
        for row in ws2.iter_rows(min_row=2):
            for cell in row:
                cell.font = Font(name=FONT, size=10)
        wo = xw.sheets['Output']
        ncols = wo.max_column
        _style_header(wo, ncols)
        headers = [wo.cell(row=1, column=i).value for i in range(1, ncols + 1)]
        for i, h in enumerate(headers, 1):
            wo.column_dimensions[get_column_letter(i)].width = WIDTH.get(h, 14)
        for r_idx in range(2, wo.max_row + 1):
            for c_idx in range(1, ncols + 1):
                cell = wo.cell(row=r_idx, column=c_idx)
                cell.font = Font(name=FONT, size=10)
                cell.alignment = Alignment(wrap_text=True, vertical='top')
                cell.border = Border(bottom=THIN)
            wo.cell(row=r_idx, column=3).fill = PatternFill('solid', start_color=FILL[lights[r_idx - 2]])
        wo.freeze_panes = 'C2'
        wo.auto_filter.ref = wo.dimensions
    return buf.getvalue()


if __name__ == '__main__':
    A, CAT = ag.load_data()
    P, S = ag.run(A, CAT)
    os.makedirs('output', exist_ok=True)
    with open(os.path.join('output', 'Razorpay_P3_Output.xlsx'), 'wb') as f:
        f.write(excel_bytes(P, S))
    print('Wrote output/Razorpay_P3_Output.xlsx  (hash %s)' % ag.output_hash(P))
