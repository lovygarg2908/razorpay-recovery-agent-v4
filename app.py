"""Merchant Onboarding Recovery Agent: Streamlit app (version 4, case-first and light).
Run locally:  streamlit run app.py
Every number and message on screen comes from agent.py, the same code the tests check.
Dry run: nothing is ever sent to a merchant. Sample data only.
"""
import contextlib
import html
import io
import json
import os
import re
import runpy

import altair as alt
import pandas as pd
import streamlit as st

import agent as ag
import make_output as MO
import messages as M
import rules as R

HERE = os.path.dirname(os.path.abspath(__file__))
st.set_page_config(page_title='Onboarding Recovery Agent', layout='wide', initial_sidebar_state='collapsed')

st.markdown("""<style>
.block-container {padding-top: 2.2rem; max-width: 1200px;}
.bubble {border-radius: 10px; padding: 14px 18px; line-height: 1.55; font-size: 0.95rem; color: #1f2937;}
.wa {background: #e7f7dd; border: 1px solid #c9e8b5;}
.em {background: #ffffff; border: 1px solid #d5dbe3;}
.em-head {font-size: 0.85rem; color: #4b5563; border-bottom: 1px solid #e5e7eb; padding-bottom: 8px; margin-bottom: 10px;}
.step-no {display:inline-block; width:28px; height:28px; line-height:28px; text-align:center; border-radius:50%;
          background:#1a56db; color:#fff; font-weight:700; margin-right:8px;}
</style>""", unsafe_allow_html=True)

LABEL = {'GREEN': 'Automatic', 'AMBER': 'Check first', 'RED': 'Person handles'}
DOT = {'GREEN': '🟢', 'AMBER': '🟠', 'RED': '🔴'}
PILL = {'GREEN': '#1e7e34', 'AMBER': '#b45309', 'RED': '#b42318'}
MEANING = {'GREEN': 'Goes out on its own after the safety check.',
           'AMBER': 'A person checks it before it goes out.',
           'RED': 'A person owns this one from start to finish.'}
CODES = ['R01', 'R02', 'R03', 'R04', 'R05', 'R06', 'R07', 'R08', 'R09', 'R10', 'R11', 'R12']
STEPS = ['Business details', 'KYC docs', 'Bank verification', 'Website/App review']
REC_TEXT = {'nudge': 'Yes', 'closure': 'No: close politely', 'hold': 'No: Compliance'}
FIXABLE_TEXT = {'Yes': 'Yes', 'No': 'No', 'Needs compliance review': 'No: Compliance'}

# Proposed product changes for the product team (proposals, not facts from the data)
PRODUCT_FIX = {
    'Name mismatch (PAN R01 + bank R03)': ('Show the name found on the PAN or bank account next to the business name, right when the merchant uploads it, '
                                           'with a one-tap choice to correct either.'),
    'R06': 'Show a checklist of the four pages needed (Terms, Privacy, Refund, Contact) and check the website link before the merchant submits.',
    'R02': 'Check the GST number against the business name and address while the merchant types it, and show any mismatch before submit.',
    'R04': 'Verify the bank account on the spot and show a clear error and retry, instead of a rejection days later.',
    'R05': 'Check the photo quality and file size at upload, and ask for a clearer picture straight away.',
    'R09': 'Show the name and date of birth read from the ID next to what was typed, before submit.',
    'R07': 'Test that the website link is public before submit and say what is missing.',
    'R08': 'Say which proof is accepted and how recent it must be, next to the upload box.',
    'R11': 'At category selection, ask for a short note or website evidence when the website looks different from the category.',
    'R13': 'Add a one-tap "What stopped you?" question when a merchant leaves, so the reason is known next time.',
}
CAUSE_NAME = {'R01': 'PAN name mismatch', 'R03': 'Bank account name mismatch', 'R02': 'GST details not verified', 'R04': 'Bank verification failed',
              'R05': 'Document unreadable', 'R06': 'Website missing policy pages', 'R07': 'Website not live', 'R08': 'Address proof missing or old',
              'R09': 'Signatory details incomplete', 'R11': 'Category differs from website', 'R13': 'Abandoned, reason unknown'}


# ---------------- helpers ----------------
def pill(light):
    return ("<span style='background:%s;color:#ffffff;padding:4px 12px;border-radius:14px;font-weight:600;font-size:0.9rem'>%s</span>"
            % (PILL.get(light, '#5f6368'), LABEL.get(light, light)))


def tag(light):
    return '%s %s' % (DOT.get(light, ''), LABEL.get(light, light))


def to_html(text):
    """Message text to simple HTML: *bold* or **bold**, line breaks kept."""
    t = html.escape(text)
    t = re.sub(r'\*\*(.+?)\*\*', r'<b>\1</b>', t)
    t = re.sub(r'\*(.+?)\*', r'<b>\1</b>', t)
    return t.replace('\n', '<br>')


def wa_bubble(text):
    return "<div class='bubble wa'>%s</div>" % to_html(text)


def email_card(subject, text, lang):
    head = "<div class='em-head'><b>To:</b> merchant (%s) &nbsp;|&nbsp; <b>From:</b> Razorpay Onboarding Team<br><b>Subject:</b> %s</div>" % (
        html.escape(lang), html.escape(subject))
    return "<div class='bubble em'>%s%s</div>" % (head, to_html(text))


def show_message(channel, subject, text, lang):
    st.markdown(email_card(subject, text, lang) if channel == 'Email' else wa_bubble(text), unsafe_allow_html=True)


@st.cache_data
def run_agent(budget_value, budget_small, extra=None):
    A, CAT = ag.load_data()
    if extra is not None:
        A = pd.concat([A, pd.DataFrame([extra])], ignore_index=True)
    return ag.run(A, CAT, budget_value, budget_small)


@st.cache_data
def message_checks():
    """Same loops as test_agent.py: every message variant through the safety checker."""
    n = fails = 0
    for lang in M.LANGS:
        for code in list(M.BODY):
            for tone in ['soft', 'reminder', 'gentle']:
                for stuck in [False, True]:
                    for ch in ['WhatsApp', 'Email']:
                        for step in (['Business details', 'KYC docs', 'Bank verification'] if code == 'R13' else [None]):
                            n += 1
                            fails += bool(R.check(M.day0(code, lang, tone=tone, channel=ch, stuck=stuck, step=step), 'nudge', lang, code, ch,
                                                  True if ch == 'WhatsApp' else None))
            for step in (STEPS if code == 'R13' else [None]):
                for fn in (M.day3, M.day7):
                    for ch in ['WhatsApp', 'Email']:
                        m = M.wrap(fn(code, lang, step), lang, ch)
                        n += 1
                        fails += bool(R.check(m, 'nudge', lang, code, ch, True if ch == 'WhatsApp' else None))
    return n, fails


@st.cache_data
def app_checks():
    """Runs test_agent.py and returns its PASS/FAIL lines, so the screen shows the real test result."""
    buf = io.StringIO()
    cwd = os.getcwd()
    try:
        os.chdir(HERE)
        with contextlib.redirect_stdout(buf):
            runpy.run_path(os.path.join(HERE, 'test_agent.py'))
    finally:
        os.chdir(cwd)
    rows = [l for l in buf.getvalue().splitlines() if l.startswith(('PASS ', 'FAIL '))]
    return [(l[:4], l[5:]) for l in rows]


def gold_results():
    path = os.path.join(HERE, 'gold_results.json')
    if os.path.exists(path):
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    return None


# ---------------- settings (hidden by default) ----------------
with st.sidebar:
    st.subheader('Settings (optional)')
    st.caption('How many merchants get a phone call this week. The defaults are 8 + 2.')
    bv = st.slider('Calls for the highest-value merchants', 0, 15, 8)
    bs = st.slider('Calls for stuck small merchants', 0, 5, 2)

P, S = run_agent(bv, bs)
T = ag.output_table(P)
lt = S['lights']
REC = P[P.kind == 'nudge']

st.title('Merchant Onboarding Recovery Agent')
st.caption('For every stalled application: why it stalled, the fix in the merchant\'s language, whether it can be recovered, and the drafted message. '
           'Sample data only. Nothing is ever sent.')

tabs = st.tabs(['Summary', 'Applications', 'Product team', 'Safety and tests', 'More'])


# ---------------- Summary ----------------
with tabs[0]:
    k = st.columns(3)
    k[0].metric('Applications that can be recovered', '%d of %d' % (S['recoverable'], S['in_scope']),
                help='100 applications were read. 25 are already activated, so 75 are in scope.')
    k[1].metric('Payments at stake (Rs lakh a month)', '%.1f' % S['recoverable_tpv'],
                help='Expected monthly payment volume (TPV) of the recoverable merchants. An estimate of what is at stake, not money recovered.')
    k[2].metric('Need a person before anything goes out', lt.get('AMBER', 0) + lt.get('RED', 0), help='Check first plus Person handles.')

    a, b = st.columns(2)
    with a.container(border=True):
        st.markdown('**What happens to the %d applications**' % S['in_scope'])
        st.markdown('- **%d** recoverable: a fix message is drafted\n- **%d** not recoverable: closed politely after a person approves\n'
                    '- **%d** go to Compliance: a neutral holding note only' % (S['recoverable'], S['closures'], S['holds']))
        st.markdown('%s &nbsp; **%d** &nbsp; %s &nbsp; **%d** &nbsp; %s &nbsp; **%d**' % (
            pill('GREEN'), lt.get('GREEN', 0), pill('AMBER'), lt.get('AMBER', 0), pill('RED'), lt.get('RED', 0)), unsafe_allow_html=True)
        st.caption('Automatic: goes out after the safety check. Check first: a person checks it. Person handles: a person owns it.')
    with b.container(border=True):
        st.markdown('**Channel and language**')
        st.markdown('- **%d** get WhatsApp (they opted in)\n- **%d** get email (not opted in), each with a subject line' % (S['whatsapp'], S['email']))
        lang_counts = P.language.value_counts()
        st.caption('Languages: ' + ', '.join('%s %d' % (l, n) for l, n in lang_counts.items()))

    st.subheader('Top three fixable causes (for the product team)')
    grp = {}
    for r_ in S['by_code']:
        code = r_['code']
        key = 'Name mismatch (PAN R01 + bank R03)' if code in ('R01', 'R03') else code
        g = grp.setdefault(key, [0, 0.0])
        g[0] += int(r_['n']); g[1] += float(r_['tpv'])
    ranked = sorted([(k_, v[0], round(v[1], 1)) for k_, v in grp.items() if k_ != 'R13'], key=lambda x: (-x[1], -x[2]))[:3]
    c = st.columns(3)
    for col, (key, n, tp) in zip(c, ranked):
        with col.container(border=True):
            nm = key if key.startswith('Name') else CAUSE_NAME.get(key, key)
            st.markdown('**%s**' % nm.replace(' (PAN R01 + bank R03)', ''))
            st.markdown('%d merchants, Rs %.1f lakh a month' % (n, tp))
            st.caption(PRODUCT_FIX.get(key, ''))
    r13 = grp.get('R13', [0, 0])
    st.caption('Not counted above: %d merchants (Rs %.1f lakh a month) stopped with no reason recorded. The agent never guesses a reason for them. '
               'See the Product team tab for every cause.' % (r13[0], r13[1]))
    st.download_button('Download the full output table (Excel)', MO.excel_bytes(P, S), 'Razorpay_P3_Output.xlsx',
                       'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


# ---------------- Applications (list, then the case below) ----------------
def case_view(r):
    st.markdown('### %s &nbsp; %s' % (r.application_id, pill(r.light)), unsafe_allow_html=True)
    st.caption('%s  |  Payments Rs %.1f lakh a month  |  Idle %d days  |  Stopped at: %s  |  Language: %s  |  Channel: %s'
               % (r.btype, r.tpv, r.days, r.step, r.language, r.channel))
    if r.data_flag:
        st.warning('Data note: ' + r.data_flag)

    # 1. Why it stalled
    with st.container(border=True):
        st.markdown("<span class='step-no'>1</span> **Why it stalled**", unsafe_allow_html=True)
        st.write(r.cause)
        st.caption('How we know: %s.' % r.evidence)
        if r.reviewer_text:
            st.caption('Reviewer note: "%s"' % r.reviewer_text)
        if r.ai_note:
            st.caption('AI second opinion: %s.' % r.ai_note)

    # 2. The fix in plain language
    with st.container(border=True):
        st.markdown("<span class='step-no'>2</span> **The fix, in simple words**", unsafe_allow_html=True)
        if r.kind == 'nudge':
            step = r.step if r.code == 'R13' else None
            lead, label, bullets = M._problem_and_bullets(r.code, r.language, step)
            lead_e, label_e, bullets_e = M._problem_and_bullets(r.code, 'English', step)
            if r.language == 'English':
                st.markdown("<div class='bubble em'>%s</div>" % to_html('%s\n\n%s\n%s' % (lead, label, '\n'.join('• ' + b for b in bullets))),
                            unsafe_allow_html=True)
            else:
                x, y = st.columns(2)
                x.caption('In %s (what the merchant reads)' % r.language)
                x.markdown("<div class='bubble em'>%s</div>" % to_html('%s\n\n%s\n%s' % (lead, label, '\n'.join('• ' + b for b in bullets))),
                           unsafe_allow_html=True)
                y.caption('In English (for the person checking)')
                y.markdown("<div class='bubble em'>%s</div>" % to_html('%s\n\n%s\n%s' % (lead_e, label_e, '\n'.join('• ' + b for b in bullets_e))),
                           unsafe_allow_html=True)
        elif r.kind == 'closure':
            st.write('No fix is offered. This is a restricted business category, and the message never suggests a workaround.')
        elif r.kind == 'hold':
            st.write('No fix is explained. The merchant is told only that the application is under review. The reason is never shared.')
        else:
            st.write('No fix is drafted because the cause is unclear. A person reads the case first.')

    # 3. Decision
    with st.container(border=True):
        st.markdown("<span class='step-no'>3</span> **Decision**", unsafe_allow_html=True)
        d1, d2, d3 = st.columns(3)
        d1.markdown('**Fixable?**  \n%s' % FIXABLE_TEXT.get(r.fixable, r.fixable))
        d2.markdown('**Recoverable?**  \n%s' % REC_TEXT.get(r.kind, 'Unclear: a person decides'))
        d3.markdown('**Who handles it**  \n%s' % r.owner)
        st.write('**What happens:** %s' % r.action)
        st.caption('%s %s' % (MEANING.get(r.light, ''), r.hold_reason))
        if r.call_slot in ag.CALLED:
            st.success('Call this week. Open with the problem and the fix above, confirm they got the written message, and ask what is blocking them. '
                       'Never mention screening, risk or approval odds.')

    # 4. Drafted nudge
    with st.container(border=True):
        st.markdown("<span class='step-no'>4</span> **The drafted message**", unsafe_allow_html=True)
        if not r.msg:
            st.write('No message is drafted for this case. A person reads it and decides.')
        else:
            why = 'opted in to WhatsApp' if r.opted else 'not opted in to WhatsApp, so email'
            st.caption('Channel: %s (%s). Language: %s. Safety check: %s.' % (r.channel, why, r.language, r.guardrail_result.lower()))
            parts = [('Day 0', r.email_subject, r.msg)]
            if r.day3:
                parts.append(('Day 3', r.subject3, r.day3))
            if r.day7:
                parts.append(('Day 7', r.subject7 or r.email_subject, r.day7))
            tab_objs = st.tabs([p[0] for p in parts])
            for tb, (name, subj, text) in zip(tab_objs, parts):
                with tb:
                    show_message(r.channel, subj, text, r.language)
            if r.language != 'English':
                with st.expander('Show the Day 0 message in English'):
                    eng = r.eng if r.channel == 'Email' else r.eng
                    show_message(r.channel, ('Your Razorpay setup: here is how to continue' if r.kind == 'nudge' else 'Your Razorpay application'), eng, 'English')
            if r.kind == 'nudge' and r.days > 30:
                st.caption('Idle 31 days or more: one gentle message only, no Day 3 or Day 7.')

    with st.expander('More details: how the agent decided'):
        steps = ['Status is %s, so the application is in scope.' % r.status, 'Cause: %s (%s).' % (r.cause, r.evidence)]
        if r.ai_note:
            steps.append('AI second opinion: %s.' % r.ai_note)
        steps.append('Route: %s.' % {'nudge': 'recoverable, message sequence', 'closure': 'polite closure, a person approves',
                                      'hold': 'Compliance holding note'}.get(r.kind, 'a person decides, no message'))
        if r.kind == 'nudge':
            steps.append('Priority score %.1f (rank %s). Call this week: %s.' % (r.score, r.priority_rank, r.call_slot or 'no'))
            steps.append('Tone from days idle: %s. Empathy line: %s.' % (ag.tone(r.days), 'yes' if r.stuck else 'no'))
        steps.append('Channel: %s.' % r.channel)
        st.write('\n\n'.join('%d. %s' % (i, s) for i, s in enumerate(steps, 1)))
        st.caption('Attempts: %d. Support contacts: %d.' % (r.attempts, r.contacts))


with tabs[1]:
    f1, f2 = st.columns([3, 2])
    show = f1.radio('Show', ['All', 'Can be recovered', 'Closed or Compliance', 'Needs a person'], horizontal=True, label_visibility='collapsed')
    langs = f2.multiselect('Language', sorted(T['Language'].unique()), placeholder='All languages', label_visibility='collapsed')
    Q = T.copy()
    if show == 'Can be recovered':
        Q = Q[Q['Recoverable'] == 'Yes']
    elif show == 'Closed or Compliance':
        Q = Q[Q['Recoverable'] != 'Yes']
    elif show == 'Needs a person':
        Q = Q[Q['Light'].isin(['AMBER', 'RED'])]
    if langs:
        Q = Q[Q['Language'].isin(langs)]
    kind_of = P.set_index('application_id').kind
    Q = Q.assign(_k=Q['Application'].map(kind_of).map(lambda k_: REC_TEXT.get(k_, 'Unclear: a person decides')))
    V = pd.DataFrame({
        'Application': Q['Application'],
        'Status': Q['Light'].map(tag),
        'Why it stalled': Q['Diagnosed cause'].map(lambda c: c.split(': ', 1)[1] if ': ' in c else c),
        'Fixable': Q['Fixable'].map(lambda x: FIXABLE_TEXT.get(x, x)),
        'Recoverable': Q['_k'],
        'Language': Q['Language'],
        'Channel': Q['Channel'],
        'Payments (Rs lakh)': Q['Expected TPV (Rs lakh)'],
    }).reset_index(drop=True)
    st.caption('%d applications. Click a row to see its full case below.' % len(V))
    ev = st.dataframe(V, hide_index=True, width='stretch', height=300, on_select='rerun', selection_mode='single-row')
    chosen = V.iloc[ev.selection.rows[0]]['Application'] if ev.selection.rows and ev.selection.rows[0] < len(V) else (V.iloc[0]['Application'] if len(V) else None)
    if chosen:
        st.divider()
        case_view(P[P.application_id == chosen].iloc[0])


# ---------------- Product team ----------------
with tabs[2]:
    st.subheader('Which fixable causes block the most merchants')
    st.write('Only recoverable applications are counted. Name mismatch groups the PAN and bank-account cases because one product change fixes both.')
    rank_by = st.radio('Rank by', ['Merchants affected', 'Payments at stake'], horizontal=True)
    rows = []
    for key, (n, tp) in grp.items():
        if key == 'R13':
            continue
        nm = 'Name mismatch (PAN and bank account)' if key.startswith('Name') else CAUSE_NAME.get(key, key)
        rows.append({'Cause': nm, 'Merchants': n, 'Payments (Rs lakh a month)': round(tp, 1),
                     'Share of recoverable merchants': '%d%%' % round(100 * n / max(S['recoverable'], 1)), '_k': key})
    CT = pd.DataFrame(rows)
    sortcol = 'Merchants' if rank_by == 'Merchants affected' else 'Payments (Rs lakh a month)'
    CT = CT.sort_values(sortcol, ascending=False).reset_index(drop=True)
    st.altair_chart(alt.Chart(CT).mark_bar(color='#1a56db').encode(
        x=alt.X('%s:Q' % sortcol, title=sortcol), y=alt.Y('Cause:N', sort=None, title=None, axis=alt.Axis(labelLimit=300)),
        tooltip=['Cause', 'Merchants', 'Payments (Rs lakh a month)']).properties(height=280), width='stretch')
    st.dataframe(CT.drop(columns='_k'), hide_index=True, width='stretch', height=370)
    st.info('**Fix this first:** show the name found on the PAN or bank account next to the business name when the merchant uploads it. '
            'It covers %d applications and Rs %.1f lakh a month. How we would know it worked: fewer name-mismatch rejections per 100 applications.'
            % (grp['Name mismatch (PAN R01 + bank R03)'][0], grp['Name mismatch (PAN R01 + bank R03)'][1]))
    with st.expander('Proposed product change for every cause'):
        for _, row_ in CT.iterrows():
            st.markdown('- **%s:** %s' % (row_['Cause'], PRODUCT_FIX.get(row_['_k'], '')))
        st.markdown('- **Abandoned, reason unknown:** %s' % PRODUCT_FIX['R13'])
    st.caption('Not ranked above: %d abandoned merchants (Rs %.1f lakh a month), the largest group. Their reason is unknown, so they are not a named cause.'
               % (r13[0], r13[1]))


# ---------------- Safety and tests ----------------
with tabs[3]:
    n_var, n_fail = message_checks()
    checks = app_checks()
    npass = sum(1 for s_, _ in checks if s_ == 'PASS')
    k = st.columns(4)
    k[0].metric('App checks passed', '%d of %d' % (npass, len(checks)))
    k[1].metric('Messages checked', format(n_var, ','), help='Every message in six languages, both channels, every code, tone and day.')
    k[2].metric('Messages blocked by the checker', n_fail)
    k[3].metric('Output check code', ag.output_hash(P), help='Same input gives the same code on every run.')
    with st.expander('See every app check'):
        for s_, name in checks:
            st.write('%s %s' % ('✅' if s_ == 'PASS' else '❌', name))

    st.subheader('Hand-labelled test set')
    G = gold_results()
    if G:
        g = st.columns(3)
        g[0].metric('Cause matched my label', '%d of %d' % (G['cause_ok'], G['n']))
        g[1].metric('Route matched my label', '%d of %d' % (G['route_ok'], G['n']))
        g[2].metric('Safety routes correct', '%d of %d' % (G['safety_ok'], G['safety_n']))
        if G.get('misses'):
            st.markdown('**Where the agent differed from my label**')
            st.dataframe(pd.DataFrame(G['misses']), hide_index=True, width='stretch')
        else:
            st.write('No differences.')
        st.caption('This is a self-check by the builder, not an independent score.')
    else:
        st.write('30 applications were labelled by hand before looking at the agent\'s answers (all 4 blank-code cases, all closure and Compliance cases, and 19 random others). '
                 'Scores are added here once the labels are compared.')

    st.subheader('A hard case: A3051')
    row = P[P.application_id == 'A3051']
    if len(row):
        r = row.iloc[0]
        st.write('There is no rejection code, only the note **"%s"**. A system that sees a blank code would treat it as a normal stall and send a fix message.' % r.reviewer_text)
        st.write('The agent reads the text for safety signals first. %s. Decision: **%s**. No fix message is drafted.' % (r.ai_note, r.decision))

    st.subheader('Try the safety checker')
    st.write('Paste any message and see whether the checker would block it.')
    examples = {   # text, type, language, code, channel
        'A safe approved message': (M.day0('R01', 'English', tone='soft', channel='WhatsApp'), 'nudge', 'English', 'R01', 'WhatsApp'),
        'Promises approval and a date': ('Dear Valued Merchant, your account will be approved within 2 days. Continue here: [resume link]\nReply "STOP" to stop these messages.', 'nudge', 'English', 'R01', 'WhatsApp'),
        'Reveals a screening reason': ('Dear Valued Merchant, your application is on hold due to compliance screening. Continue here: [resume link]\nReply "STOP" to stop these messages.', 'nudge', 'English', 'R01', 'WhatsApp'),
        'Closure that suggests a workaround': ('Dear Valued Merchant, we cannot support this business. You can reapply under a different category instead.', 'closure', 'English', 'R10', 'Email'),
        'Holding note that reveals screening': ('Dear Valued Merchant, your application is paused after a sanctions screening match.', 'hold', 'English', 'R12', 'Email'),
        'WhatsApp message missing the STOP line': ('Dear Valued Merchant, please upload a clear document. Continue here: [resume link]', 'nudge', 'English', 'R05', 'WhatsApp'),
        'Hindi message written in Latin letters': ('Kripya apna PAN upload karein. Continue here: [resume link]\nReply "STOP" to stop these messages.', 'nudge', 'Hindi', 'R01', 'WhatsApp'),
    }
    PLAIN = {'forbidden word (EN)': 'uses a banned word: a promise, a compliance reason or a workaround',
             'forbidden token (Hinglish)': 'uses a banned Hinglish word such as aaj or kal',
             'forbidden word (native script)': 'uses a banned word in the regional script',
             'forbidden token (native script)': 'uses a banned regional word such as today or tomorrow',
             'number or date present': 'contains a number or date (only "5 MB" is allowed)',
             'missing resume link': 'has no resume link', 'no resume link in closure/hold': 'a closure or holding note must not carry a link',
             'closure/hold wording not allowed': 'suggests a workaround or reveals a reason',
             'WhatsApp message too long': 'is longer than 1,000 characters for WhatsApp',
             'WhatsApp nudge missing STOP line': 'has no "Reply STOP" line, which WhatsApp nudges need',
             'WhatsApp nudge missing HELP line': 'has no "HELP" line, which WhatsApp nudges need',
             'emoji present': 'contains an emoji, which Razorpay messages do not use',
             'WhatsApp without opt-in': 'goes to WhatsApp without opt-in', 'wrong script for language': 'is in the wrong script for the language',
             'unfilled placeholder': 'has an unfilled placeholder', 'R13 must not guess a reason': 'guesses a reason for an abandoned application',
             'never nudge this code': 'is a nudge to a closure or Compliance case'}
    pickx = st.selectbox('Start from an example', list(examples))
    ex = examples[pickx]
    txt = st.text_area('Message', ex[0], height=170, key='gt-' + pickx)
    with st.expander('Check settings (message type, language, code, channel)'):
        g1, g2, g3, g4 = st.columns(4)
        kind = g1.selectbox('Type', ['nudge', 'closure', 'hold'], index=['nudge', 'closure', 'hold'].index(ex[1]), key='gk-' + pickx)
        glang = g2.selectbox('Language', M.LANGS, index=M.LANGS.index(ex[2]), key='gl-' + pickx)
        gcode = g3.selectbox('Code', CODES + ['R13'], index=(CODES + ['R13']).index(ex[3]), key='gc-' + pickx)
        gch = g4.selectbox('Channel', ['WhatsApp', 'Email'], index=['WhatsApp', 'Email'].index(ex[4]), key='gh-' + pickx)
    fails = R.check(txt, kind, glang, gcode, gch, True if gch == 'WhatsApp' else None)
    if fails:
        st.error('Blocked. This message ' + '; it '.join(PLAIN.get(f, f) for f in fails) + '.')
    else:
        st.success('Passes every check.')
    st.caption('Known gap: a keyword checker misses vague promises such as "very soon". That is why the agent never writes free text.')


# ---------------- More ----------------
with tabs[4]:
    more = st.tabs(['How it works', 'Follow-up plan', 'Written answers', 'Outbox (simulated)', 'Message library', 'Try a case'])

    with more[0]:
        st.subheader('How it works')
        st.markdown('''
1. **Read** every application. Activated ones are left out.
2. **Find the cause** from the catalog code. If the code is blank, simple keyword rules and a saved AI second opinion must agree, and a person confirms. If there is no code and no note, the merchant simply stopped, and the agent names the step without guessing a reason.
3. **Safety first.** Reviewer text that signals screening or a restricted business beats any fixable code.
4. **Decide.** Restricted business: polite closure after a person approves. Screening: Compliance holding note. Unclear: a person decides. Everything else can be recovered.
5. **Pick who to call.** Priority = payment volume x how recent x how easy x how sure we are. The top 8 get a call, plus 2 stuck small merchants. Everyone still gets the written message.
6. **Write** the message from approved pieces in the merchant's language: problem, fix, why it matters, one link, help line.
7. **Choose the channel.** WhatsApp only if the merchant opted in. Everyone else gets an email with a subject line and sign-off.
8. **Check** every message: no promises, dates, compliance reasons, workarounds or wrong script.
9. **Label** every case Automatic, Check first or Person handles.
''')
        st.markdown('**What AI does:** reads blank-code reviewer notes as a second opinion only. Its answers were produced once and saved, so every run is identical. '
                    'AI never picks a route, closes an application, contacts Compliance or writes message text.')
        st.markdown('**Language:** the Tamil, Kannada and Marathi messages were reviewed and approved by native speakers, so they go out like any other language.')
        st.markdown('**Limits, stated openly:** no outcome data, so no recovery rate is claimed. The Compliance holding-note wording still needs Compliance sign-off. '
                    '21 rows have idle days longer than the account age; they are flagged, not changed.')

    with more[1]:
        st.subheader('Follow-up plan')
        seq = pd.DataFrame([
            ['Day 0', 'The first message: problem, fix, link', 'Always (a closure or Compliance case gets its own note)'],
            ['Day 3', 'A short reminder with the steps left', 'Only if idle 30 days or less and the merchant has not replied or finished'],
            ['Day 7', 'A short offer of help', 'Same as Day 3'],
            ['Phone call', 'Top 8 by value plus 2 stuck small merchants, this week', 'The written message still goes as backup']],
            columns=['When', 'What', 'Rule'])
        st.dataframe(seq, hide_index=True, width='stretch')
        st.markdown('**The sequence stops when** the merchant replies, finishes the application, opts out (STOP), or three messages have gone. '
                    'A HELP reply goes to a person. Messages go out only between 9am and 7pm India time. '
                    'The opener changes with days idle: up to 7 days a thank-you, 8 to 30 days a reminder, 31 or more a gentle line.')

    with more[2]:
        st.subheader('The written answers, with live numbers')
        st.write('Each answer in the submission can be checked against this app. Numbers below come from the running agent.')
        nvars, nfails = message_checks()
        ans = pd.DataFrame([
            ['1. Problem and main user', 'Onboarding Ops team (and the RMs who call). %d stalled applications.' % S['in_scope'], 'Summary'],
            ['2. Outcome in numbers', '%d recoverable, Rs %.1f lakh a month at stake. No recovery rate is claimed.' % (S['recoverable'], S['recoverable_tpv']), 'Summary'],
            ['3. What AI does', 'Second opinion on the 4 blank-code notes only. Rules do the rest. No free text to merchants.', 'Applications (open A3022, A3028, A3051, A3081)'],
            ['4. Tools', 'Claude for building, Python and Streamlit, GitHub, Streamlit Community Cloud.', 'README'],
            ['5. Testing', '%s message variants checked, %d blocked. Hand-labelled set of 30 cases.' % (format(nvars, ','), nfails), 'Safety and tests'],
            ['6. A real failure', 'A3051: blank code but a "not supported" note. Handled as a restricted business, never a fix message.', 'Safety and tests'],
            ['7. Risks and controls', 'Safety checker, person approves closures, Compliance owns holds, 2 of 10 calls go to small merchants, no real data, nothing sent.', 'Safety and tests, Follow-up plan'],
            ['8. Next 3 months', 'Live pilot with a holdout group, about 200 labelled cases, ship the first product fix.', 'Product team'],
            ['9. Fixable or compliance', '%d closures and %d Compliance cases held for people. Text signals beat the code.' % (S['closures'], S['holds']), 'Applications (filter: Closed or Compliance)'],
            ['10. Language, channel, timing', '6 languages. %d WhatsApp (opted in), %d email. Day 0, 3 and 7 with stop rules.' % (S['whatsapp'], S['email']), 'Applications, Follow-up plan'],
            ['11. First product fix', 'Show the PAN or bank name next to the business name at upload.', 'Product team']],
            columns=['Question', 'What the app shows', 'Where to look'])
        st.dataframe(ans, hide_index=True, width='stretch', height=430)

    with more[3]:
        st.subheader('Outbox (simulated: nothing is sent)')
        st.write('Shows what would go out, to whom, on which channel and day, between 9am and 7pm India time. '
                 'Approve held messages, or mark a merchant as replied or activated to watch the follow-ups stop.')
        day0 = pd.Timestamp(st.date_input('Day 0 (first send day)', pd.Timestamp('2026-10-01')))
        if 'approved' not in st.session_state:
            st.session_state.approved, st.session_state.stopped = set(), set()
        waiting = P[(P.msg != '') & (P.light != 'GREEN')].application_id.tolist()
        x1, x2 = st.columns(2)
        appr = x1.multiselect('Approve held messages (a person has checked them)', waiting)
        stop = x2.multiselect('Merchant replied, activated or opted out', P[P.kind == 'nudge'].application_id.tolist())
        if x1.button('Save approvals'):
            st.session_state.approved |= set(appr)
        if x2.button('Stop their sequence'):
            st.session_state.stopped |= set(stop)
        rows = []
        for r in P[P.msg != ''].itertuples():
            held = r.light != 'GREEN' and r.application_id not in st.session_state.approved
            for n, text in [(0, r.msg), (3, r.day3), (7, r.day7)]:
                if not text:
                    continue
                if r.kind == 'hold' and n == 3:
                    continue
                if r.application_id in st.session_state.stopped and n > 0:
                    state = 'Cancelled: merchant replied or activated'
                elif held:
                    state = 'Held: ' + r.send_status
                else:
                    state = 'Queued (simulated, not sent)'
                rows.append({'Merchant': r.application_id, 'Status': tag(r.light), 'Message': 'Day %d' % n,
                             'Send date': (day0 + pd.Timedelta(days=n)).strftime('%d %b %Y') + ', 9am to 7pm',
                             'Channel': r.channel, 'Language': r.language, 'State': state})
        O = pd.DataFrame(rows)
        s1, s2, s3 = st.columns(3)
        s1.metric('Queued', int(O.State.str.startswith('Queued').sum()))
        s2.metric('Held for a person', int(O.State.str.startswith('Held').sum()))
        s3.metric('Cancelled by stop rules', int(O.State.str.startswith('Cancelled').sum()))
        st.dataframe(O, hide_index=True, width='stretch', height=420)
        st.markdown('**Try a merchant reply**')
        rep = st.text_input('What the merchant replies (try HELP, STOP, or anything else)', 'HELP')
        act, why = ag.handle_reply(rep)
        st.info('**%s.** %s' % (act, why))

    with more[4]:
        st.subheader('Approved message library')
        st.write('Every message is built only from these pieces. The Tamil, Kannada and Marathi wording was reviewed and approved by native speakers.')
        ll = st.selectbox('Language', M.LANGS, key='lib-lang')
        lib = [('Greeting', M.GREET[ll]), ('Opener, idle 7 days or less', M.OPEN_TONE['soft'][ll]), ('Opener, idle 8 to 30 days', M.OPEN_TONE['reminder'][ll]),
               ('Opener, idle 31 days or more', M.OPEN_TONE['gentle'][ll])]
        lib += [('Steps line, %s left' % w, M.STEPS[ll][i]) for i, w in enumerate(['one step', 'two steps', 'three steps', 'four steps'])]
        lib += [('Empathy line (stuck merchants)', M.EMPATHY[ll]), ('Fix label, choose one', M.FIX_LABEL['choose'][ll]), ('Fix label, steps to do', M.FIX_LABEL['do'][ll]),
                ('Fix label, abandoned', M.FIX_LABEL['r13'][ll]), ('Why it matters', M.WHY[ll]), ('Link line', M.CTA[ll]),
                ('Help line (WhatsApp)', M.HELP_W[ll]), ('Help line (email)', M.HELP_E[ll]), ('Opt-out line (WhatsApp)', M.STOP[ll]), ('Sign-off (email)', M.SIGN[ll]),
                ('Email subject, Day 0', M.SUBJ['day0'][ll]), ('Email subject, Day 3', M.SUBJ['day3'][ll]), ('Email subject, Day 7', M.SUBJ['day7'][ll]),
                ('Email subject, closure or holding note', M.SUBJ['plain'][ll])]
        lib += [('%s problem' % k_, v[ll][0]) for k_, v in M.BODY.items()] + [('%s fix' % k_, v[ll][1]) for k_, v in M.BODY.items()]
        lib += [('R10 closure', M.CLOSE[ll]), ('R12 holding note, Day 0', M.HOLD0[ll]), ('R12 holding note, Day 7', M.HOLD7[ll])]
        st.dataframe(pd.DataFrame(lib, columns=['Piece', 'Text']), hide_index=True, width='stretch', height=460)

    with more[5]:
        st.subheader('Try a case')
        st.write('Make up an application and run it through the same agent. It is added to the 100 real rows, so its rank and call slot are real too.')
        with st.form('try'):
            a, b, c4 = st.columns(3)
            code = a.selectbox('Rejection code', ['(blank)'] + CODES, index=1)
            text = a.text_area('Reviewer note (optional)', '')
            status = a.selectbox('Status', ['Stalled', 'Rejected'])
            step = b.selectbox('Step reached', STEPS, index=1)
            lang = b.selectbox('Preferred language', M.LANGS)
            opted = b.radio('Opted in to WhatsApp?', ['Yes', 'No'], horizontal=True)
            days = c4.number_input('Days since last activity', 0, 120, 5)
            attempts = c4.number_input('Attempts', 1, 10, 1)
            contacts = c4.number_input('Support contacts', 0, 10, 0)
            tpv = c4.number_input('Expected payments (Rs lakh a month)', 0.1, 500.0, 12.0)
            go = st.form_submit_button('Run the agent on this case')
        if go:
            extra = dict(application_id='TEST', business_type='Proprietorship', industry='Test', city='Test', preferred_language=lang,
                         signup_date='01 Sep 2026', expected_monthly_tpv_inr_lakh=float(tpv), whatsapp_opted_in=opted,
                         step_reached=step, application_status=status, days_since_last_activity=int(days), attempts=int(attempts),
                         support_contacts=int(contacts), rejection_code=None if code == '(blank)' else code,
                         rejection_message=text.strip() or None)
            PT, _ = run_agent(bv, bs, extra)
            case_view(PT[PT.application_id == 'TEST'].iloc[0])
