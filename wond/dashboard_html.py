from __future__ import annotations

DASHBOARD_HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Wond Dashboard</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --panel-2: #f0f3f6;
      --text: #16181d;
      --muted: #626b77;
      --line: #d9dee7;
      --ok: #127a4a;
      --warn: #a85f00;
      --fail: #b3261e;
      --info: #225a9b;
      --accent: #2457c5;
      --accent-2: #0f766e;
      --shadow: 0 12px 32px rgba(16, 24, 40, .08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    * { box-sizing: border-box; }
    body { margin: 0; background: var(--bg); color: var(--text); overflow-x: hidden; }
    button, input, select, textarea { font: inherit; }
    .app { display: grid; grid-template-columns: 236px 1fr; min-height: 100vh; }
    aside { background: #10141b; color: #e5e7eb; padding: 18px 14px; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
    .brand { display: flex; gap: 10px; align-items: center; padding: 6px 8px 16px; }
    .mark { width: 34px; height: 34px; border-radius: 8px; background: linear-gradient(135deg, #4f7cff, #0f766e); }
    .brand h1 { margin: 0; font-size: 17px; line-height: 1.2; }
    .brand span { display: block; color: #aeb7c5; font-size: 12px; margin-top: 3px; }
    nav { display: grid; gap: 12px; }
    .nav-group { display: grid; gap: 3px; }
    .nav-label { color: #7d8798; font-size: 11px; font-weight: 750; padding: 0 9px 2px; }
    nav button { display: flex; width: 100%; gap: 10px; align-items: center; border: 0; background: transparent; color: #cbd5e1; padding: 9px 10px; border-radius: 8px; text-align: left; cursor: pointer; font-weight: 650; }
    nav button.active, nav button:hover { background: rgba(255,255,255,.11); color: #fff; }
    main { padding: 22px 24px 28px; min-width: 0; }
    .topbar { display: flex; justify-content: space-between; align-items: flex-start; gap: 18px; margin-bottom: 18px; }
    h2 { margin: 0; font-size: 26px; letter-spacing: 0; }
    .subtitle { margin-top: 5px; color: var(--muted); }
    .toolbar { display: flex; flex: 1; flex-wrap: wrap; gap: 8px; justify-content: flex-end; align-items: center; }
    .section-tabs { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-start; }
    .toolbar .section-tabs { margin-right: auto; }
    .btn { border: 1px solid var(--line); background: var(--panel); color: var(--text); padding: 8px 11px; border-radius: 8px; cursor: pointer; box-shadow: 0 1px 0 rgba(16,24,40,.04); }
    .btn.primary { background: var(--accent); border-color: var(--accent); color: #fff; }
    .btn.danger { color: var(--fail); }
    .grid { display: grid; gap: 14px; }
    .grid.cols-4 { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .grid.cols-3 { grid-template-columns: repeat(3, minmax(0, 1fr)); }
    .grid.cols-2 { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .card { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; box-shadow: 0 1px 2px rgba(16, 24, 40, .06); padding: 15px; min-width: 0; overflow-wrap: anywhere; }
    .metric .label { color: var(--muted); font-size: 13px; }
    .metric .value { font-size: 30px; font-weight: 700; margin-top: 7px; }
    .metric .hint { color: var(--muted); font-size: 12px; margin-top: 5px; }
    .status { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; }
    .status.ok { background: #dff7ea; color: var(--ok); }
    .status.warn { background: #fff1d6; color: var(--warn); }
    .status.fail { background: #fde7e5; color: var(--fail); }
    .status.error { background: #fde7e5; color: var(--fail); }
    .status.missing_file { background: #fff1d6; color: var(--warn); }
    .status.unavailable, .status.empty, .status.keyword-fallback, .status.extractive { background: #fff1d6; color: var(--warn); }
    .status.semantic-rag, .status.ollama-keyword { background: #e0f2fe; color: #075985; }
    .status.processing { background: #e0f2fe; color: #075985; }
    .status.skipped { background: #edf2f7; color: #4b5563; }
    .status.observation { background: #e5eefb; color: var(--info); }
    .status.activity { background: #e8f4ef; color: var(--ok); }
    .status.reports, .status.daily, .status.weekly, .status.monthly, .status.email, .status.feedback { background: #edf2f7; color: #374151; }
    .status.provisional, .status.below_threshold { background: #fff1d6; color: var(--warn); }
    .status.auto_merged_pending_review { background: #fff1d6; color: var(--warn); }
    .status.low_similarity_hidden { background: #edf2f7; color: #4b5563; }
    .status.confirmed, .status.accepted, .status.named { background: #dff7ea; color: var(--ok); }
    .status.disabled { background: #edf2f7; color: #4b5563; }
    .status.info, .status.pending { background: #e5eefb; color: var(--info); }
    .status.high { background: #fde7e5; color: var(--fail); }
    .status.medium { background: #fff1d6; color: var(--warn); }
    .status.low { background: #edf2f7; color: #4b5563; }
    .status.open { background: #e5eefb; color: var(--info); }
    .status.snoozed { background: #fff1d6; color: var(--warn); }
    .status.done { background: #dff7ea; color: var(--ok); }
    .status.archived, .status.dismissed { background: #edf2f7; color: #4b5563; }
    table { width: 100%; border-collapse: collapse; font-size: 13px; }
    th, td { padding: 10px 8px; border-bottom: 1px solid var(--line); text-align: left; vertical-align: top; }
    th { color: var(--muted); font-weight: 700; background: var(--panel-2); position: sticky; top: 0; z-index: 1; }
    .table-wrap { max-height: 560px; overflow: auto; border: 1px solid var(--line); border-radius: 8px; }
    .muted { color: var(--muted); }
    .mono { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .split { display: grid; grid-template-columns: 360px 1fr; gap: 14px; align-items: start; }
    .list { display: grid; gap: 8px; }
    .item { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: var(--panel); cursor: pointer; }
    .item:hover { border-color: #aeb8c9; }
    .item-title { font-weight: 700; }
    .item-meta { color: var(--muted); font-size: 12px; margin-top: 3px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #0b1020; color: #e5e7eb; padding: 14px; border-radius: 8px; overflow: auto; max-height: 620px; }
    .reports-layout { display: grid; grid-template-columns: 300px minmax(0, 1fr) 300px; gap: 14px; align-items: start; }
    .reports-layout > * { min-width: 0; }
    .reports-nav, .reports-side { display: grid; gap: 14px; }
    .reports-side { position: sticky; top: 24px; }
    .reports-controls { display: grid; gap: 8px; }
    .reports-list { display: grid; gap: 8px; max-height: calc(100vh - 300px); overflow: auto; padding-right: 2px; }
    .report-file-item { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: var(--panel); cursor: pointer; min-width: 0; }
    .report-file-item:hover, .report-file-item.active { border-color: var(--accent); background: #e9f0ff; }
    .report-file-title { font-weight: 750; overflow-wrap: anywhere; }
    .report-file-meta { color: var(--muted); font-size: 12px; margin-top: 4px; display: flex; flex-wrap: wrap; gap: 4px 8px; }
    .reports-metrics { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .report-metric { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .report-metric .label { color: var(--muted); font-size: 12px; }
    .report-metric .value { font-size: 22px; font-weight: 750; margin-top: 4px; overflow-wrap: anywhere; }
    .report-reader { min-height: 720px; }
    .report-reader-header { border-bottom: 1px solid var(--line); margin: -2px 0 14px; padding-bottom: 12px; }
    .report-reader-title { font-size: 22px; font-weight: 800; line-height: 1.25; overflow-wrap: anywhere; }
    .report-reader-content { line-height: 1.65; color: var(--text); overflow-wrap: anywhere; word-break: break-word; max-height: min(720px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .report-reader-content h1 { font-size: 24px; margin: 0 0 14px; line-height: 1.25; }
    .report-reader-content h2 { font-size: 18px; margin: 22px 0 8px; padding-top: 8px; border-top: 1px solid var(--line); }
    .report-reader-content h3 { font-size: 15px; margin: 16px 0 6px; }
    .report-reader-content p { margin: 8px 0; }
    .report-reader-content ul, .report-reader-content ol { margin: 8px 0 10px 20px; padding: 0; }
    .report-reader-content li { margin: 4px 0; }
    .report-reader-content code { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; background: #edf2f7; border-radius: 5px; padding: 1px 4px; }
    .report-reader-content pre { max-height: none; margin: 10px 0; }
    .report-outline { display: grid; gap: 6px; }
    .report-outline-row { border-bottom: 1px solid var(--line); padding: 7px 0; color: var(--muted); overflow-wrap: anywhere; }
    .report-outline-row:last-child { border-bottom: 0; }
    .report-category-list { display: grid; gap: 4px; }
    .report-category-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid transparent; border-bottom-color: var(--line); border-radius: 8px; padding: 9px 8px; cursor: pointer; }
    .report-category-row:hover, .report-category-row.active { border-color: var(--accent); background: #e9f0ff; }
    .report-category-row:last-child { border-bottom-color: transparent; }
    .searchbar { display: grid; grid-template-columns: minmax(0, 1fr) 170px auto auto; gap: 8px; margin-bottom: 12px; align-items: center; }
    .search-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; }
    .search-main, .search-answer-layout { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .search-main > *, .search-answer-layout > * { min-width: 0; }
    .search-side, .search-stack, .search-answer-side { display: grid; gap: 14px; }
    .search-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }
    .search-actions .btn { min-width: 112px; }
    .search-source-pills { display: flex; flex-wrap: wrap; gap: 8px; }
    .search-index-grid, .search-metric-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .search-index-stat, .search-metric { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .search-index-stat .label, .search-metric .label { color: var(--muted); font-size: 12px; }
    .search-index-stat .value, .search-metric .value { font-size: 22px; font-weight: 750; margin-top: 4px; overflow-wrap: anywhere; }
    .search-index-stat .value.compact { font-size: 18px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
    .search-model-row, .citation-row { border-bottom: 1px solid var(--line); padding: 9px 0; }
    .search-model-row:last-child, .citation-row:last-child { border-bottom: 0; }
    .search-retrieval { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: start; margin-top: 14px; }
    .search-retrieval .section-title { margin-bottom: 0; }
    .search-error { color: var(--warn); margin-top: 8px; overflow-wrap: anywhere; }
    .search-list { display: grid; gap: 8px; }
    .search-result { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: var(--panel); min-width: 0; }
    .search-result.semantic { border-left: 4px solid var(--accent); }
    .search-result.observation { border-left: 4px solid var(--accent-2); }
    .search-result.report { border-left: 4px solid var(--warn); }
    .result-title { font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; }
    .result-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .result-text { color: var(--muted); margin-top: 6px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 5; -webkit-box-orient: vertical; overflow: hidden; }
    .search-stack .result-text { -webkit-line-clamp: 4; }
    .answer-body { line-height: 1.65; overflow-wrap: anywhere; word-break: break-word; }
    .citation-list { display: grid; gap: 0; }
    .citation-type { font-weight: 750; }
    input, select, textarea { border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; background: #fff; color: var(--text); }
    textarea { min-height: 92px; width: 100%; resize: vertical; }
    .answer { line-height: 1.6; }
    .timeline { display: grid; gap: 8px; }
    .timeline-row { display: grid; grid-template-columns: 160px 130px 1fr; gap: 10px; padding: 10px 0; border-bottom: 1px solid var(--line); }
    .timeline-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .timeline-toolbar { display: grid; grid-template-columns: 140px minmax(170px, 1fr) 145px 125px 70px; gap: 8px; align-items: center; }
    .timeline-toolbar .btn { width: 100%; }
    .timeline-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .timeline-stat { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .timeline-stat .label { color: var(--muted); font-size: 12px; }
    .timeline-stat .value { font-size: 24px; font-weight: 750; margin-top: 4px; }
    .timeline-stat .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .timeline-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .timeline-main > * { min-width: 0; }
    .timeline-side { display: grid; gap: 14px; }
    .timeline-section { display: grid; gap: 8px; margin-bottom: 16px; }
    .timeline-section-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 2px 2px 0; }
    .timeline-section-header h3 { margin: 0; font-size: 15px; }
    .timeline-feed { max-height: min(760px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .timeline-list { display: grid; gap: 8px; }
    .timeline-event { display: grid; grid-template-columns: 72px 132px minmax(0, 1fr); gap: 10px; padding: 12px; border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; background: var(--panel); min-width: 0; }
    .timeline-event.activity { border-left-color: var(--accent-2); }
    .timeline-event > * { min-width: 0; }
    .timeline-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
    .timeline-title { font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .timeline-body { color: var(--muted); margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .timeline-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .timeline-breakdown { display: grid; gap: 4px; max-height: 360px; overflow: auto; padding-right: 2px; }
    .timeline-breakdown-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid transparent; border-bottom-color: var(--line); padding: 9px 8px; border-radius: 8px; cursor: pointer; }
    .timeline-breakdown-row:hover, .timeline-breakdown-row.active { border-color: var(--accent); background: #e9f0ff; }
    .timeline-breakdown-row:last-child { border-bottom-color: transparent; }
    .sources-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .source-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .source-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .source-kpi .label { color: var(--muted); font-size: 12px; }
    .source-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .source-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .source-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .source-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .source-action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .source-action-grid .btn { width: 100%; text-align: left; }
    .sources-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .sources-main > * { min-width: 0; }
    .source-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .source-card { border: 1px solid var(--line); border-radius: 8px; background: var(--panel); padding: 13px; min-width: 0; border-left: 4px solid var(--accent); }
    .source-card.issue { border-left-color: var(--warn); }
    .source-card.disabled { border-left-color: #9aa4b2; }
    .source-card.error { border-left-color: var(--fail); }
    .source-card-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
    .source-name { font-weight: 800; font-size: 17px; line-height: 1.25; }
    .source-note-list, .source-issue-list, .source-side { display: grid; gap: 8px; }
    .source-note { border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; background: #fff8eb; color: var(--warn); line-height: 1.4; overflow-wrap: anywhere; }
    .source-run { color: var(--muted); font-size: 12px; margin-top: 8px; line-height: 1.45; overflow-wrap: anywhere; }
    .source-kind-list { display: grid; gap: 6px; margin-top: 11px; }
    .source-kind-row { display: grid; grid-template-columns: minmax(0, 1fr) 58px minmax(96px, .8fr); gap: 8px; align-items: center; border-top: 1px solid var(--line); padding-top: 7px; font-size: 12px; }
    .source-kind-row b { font-size: 13px; }
    .source-issue { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; border-left: 4px solid var(--warn); min-width: 0; }
    .source-issue.fail { border-left-color: var(--fail); }
    .source-issue-title { font-weight: 750; }
    .source-issue-body { color: var(--muted); margin-top: 4px; line-height: 1.4; overflow-wrap: anywhere; }
    .speaker-workbench { display: grid; gap: 13px; }
    .speaker-command-row { display: grid; grid-template-columns: minmax(0, 1fr); gap: 14px; align-items: start; }
    .speaker-command-copy { min-width: 0; }
    .speaker-command-copy .section-title { margin-bottom: 5px; }
    .speaker-command-note { color: var(--muted); line-height: 1.45; max-width: 720px; margin: 0; }
    .speaker-kpis { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #fbfcfe; }
    .speaker-kpi { border-right: 1px solid var(--line); padding: 10px 12px; min-width: 0; }
    .speaker-kpi:last-child { border-right: 0; }
    .speaker-kpi .label { color: var(--muted); font-size: 12px; }
    .speaker-kpi .value { font-size: 22px; font-weight: 750; margin-top: 4px; }
    .speaker-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .speaker-filter-row { display: grid; grid-template-columns: auto minmax(0, 1fr); gap: 10px; align-items: center; }
    .speaker-filter-label { color: var(--muted); font-size: 12px; font-weight: 750; }
    .speaker-filters { display: flex; flex-wrap: wrap; gap: 8px; }
    .speaker-review-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) 154px auto; gap: 8px; align-items: center; }
    .speaker-review-layout { display: grid; grid-template-columns: minmax(0, 1fr); gap: 16px; }
    .speaker-panel { display: grid; gap: 10px; min-width: 0; }
    .speaker-panel-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; }
    .speaker-panel-head h3 { margin: 0; font-size: 16px; }
    .speaker-sample-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) 150px 150px auto; gap: 8px; align-items: center; }
    .speaker-sample-filters { display: flex; flex-wrap: wrap; gap: 8px; }
    .speaker-sample-summary { display: flex; flex-wrap: wrap; gap: 6px 10px; color: var(--muted); font-size: 12px; }
    .speaker-tools { display: grid; gap: 10px; }
    .speaker-tools > *, .speaker-tools select, .speaker-tools input, .speaker-tools .btn { min-width: 0; max-width: 100%; }
    .speaker-tools select, .speaker-tools input, .speaker-tools .btn { width: 100%; }
    .speaker-tool-row { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr) auto; gap: 8px; align-items: center; }
    .speaker-action-group { border-top: 1px solid var(--line); padding-top: 10px; display: grid; gap: 8px; }
    .speaker-action-group:first-child { border-top: 0; padding-top: 0; }
    .speaker-action-title { color: var(--muted); font-size: 12px; font-weight: 750; }
    .speaker-context-card .empty-state { padding: 12px; }
    .speaker-context-summary { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; padding: 10px; display: grid; gap: 6px; }
    .speaker-context-title { font-weight: 800; line-height: 1.3; overflow-wrap: anywhere; }
    .speaker-context-note { color: var(--muted); font-size: 12px; line-height: 1.4; overflow-wrap: anywhere; }
    .speaker-context-actions { display: grid; gap: 8px; }
    .speaker-context-actions .btn { text-align: left; }
    .speaker-bulk-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .speaker-bulk-row { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; align-items: center; }
    .speaker-danger-row { border-top: 1px solid var(--line); padding-top: 10px; }
    .speaker-tool-row .btn { white-space: nowrap; }
    .speaker-selection { border: 1px solid var(--line); border-radius: 8px; background: #fbfcfe; padding: 10px; display: grid; gap: 8px; }
    .speaker-selection-title { display: flex; justify-content: space-between; gap: 10px; font-weight: 750; }
    .speaker-selection-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .speaker-selection-chip { border: 1px solid var(--line); border-radius: 8px; padding: 8px; background: var(--panel); min-width: 0; }
    .speaker-selection-chip .label { color: var(--muted); font-size: 11px; }
    .speaker-selection-chip .value { font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .speakers-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .speakers-main > * { min-width: 0; }
    .speaker-content { display: grid; gap: 14px; align-content: start; min-width: 0; }
    .speaker-list-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; margin-bottom: 10px; }
    .speaker-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
    .speaker-card { border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; background: var(--panel); padding: 12px; min-width: 0; cursor: pointer; position: relative; display: grid; gap: 9px; }
    .speaker-card.review { border-left-color: var(--warn); }
    .speaker-card.empty { border-left-color: #9aa4b2; }
    .speaker-card.hidden-speaker { border-left-color: #9aa4b2; background: #f8fafc; }
    .speaker-card.selected { border-color: var(--accent); background: #e9f0ff; }
    .speaker-card:hover { border-color: var(--accent); background: #fbfcfe; }
    .speaker-check { position: absolute; right: 11px; top: 11px; width: 20px; height: 20px; }
    .speaker-card-top { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; padding-right: 28px; }
    .speaker-name { font-size: 17px; font-weight: 800; line-height: 1.25; overflow-wrap: anywhere; }
    .speaker-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 5px; }
    .speaker-card-metrics { display: flex; flex-wrap: wrap; gap: 8px 12px; color: var(--muted); font-size: 12px; border-top: 1px solid var(--line); padding-top: 9px; }
    .speaker-card-metrics b { color: var(--text); font-size: 13px; }
    .speaker-card-actions { display: flex; flex-wrap: wrap; gap: 8px; }
    .speaker-side { display: grid; gap: 14px; }
    .speaker-match-list, .speaker-sample-list { display: grid; gap: 8px; }
    .speaker-sample-list.expanded { max-height: min(760px, calc(100vh - 220px)); }
    .speaker-match-card, .speaker-sample-card { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .speaker-sample-card { border-left: 4px solid #9aa4b2; display: grid; gap: 8px; }
    .speaker-sample-card.ok { border-left-color: var(--accent); }
    .speaker-sample-card.low-confidence, .speaker-sample-card.error { border-left-color: var(--warn); }
    .speaker-sample-card.representative { border-left-color: var(--accent-2); }
    .speaker-sample-card.missing-embedding { border-left-color: #9aa4b2; }
    .speaker-match-row { display: flex; justify-content: space-between; gap: 10px; align-items: flex-start; }
    .speaker-score { font-weight: 750; }
    .speaker-sample-card audio { width: 100%; }
    .speaker-sample-actions { display: flex; justify-content: flex-end; margin-top: 8px; }
    .speaker-sample-tags { display: flex; flex-wrap: wrap; gap: 6px; }
    .speaker-transcript { color: var(--muted); line-height: 1.45; margin-top: 6px; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .training-hero, .training-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-bottom: 14px; }
    .training-kpis, .training-stage-grid { display: grid; gap: 10px; margin-top: 12px; }
    .training-kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .training-stage-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .training-kpi, .training-stage-card { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .training-kpi .label, .training-stage-card .label { color: var(--muted); font-size: 12px; font-weight: 750; }
    .training-kpi .value { font-size: 25px; font-weight: 850; margin-top: 5px; overflow-wrap: anywhere; }
    .training-kpi .hint, .training-stage-card .hint { color: var(--muted); font-size: 12px; margin-top: 5px; overflow-wrap: anywhere; }
    .training-stage-card.blocked { border-left: 4px solid var(--warn); }
    .training-stage-card.ready { border-left: 4px solid #b7791f; }
    .training-stage-card.ok { border-left: 4px solid var(--accent); }
    .training-toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .training-list, .training-sample-list, .training-match-list { display: grid; gap: 9px; max-height: min(660px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .training-card { border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .training-card.low_confidence, .training-card.missing_embedding, .training-card.needs_scoring, .training-card.review_needed, .training-card.pending_auto { border-left-color: var(--warn); }
    .training-card.hidden, .training-card.empty { border-left-color: #9aa4b2; opacity: .84; }
    .training-card.confirmed, .training-card.stable { border-left-color: var(--accent-2); }
    .training-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; min-width: 0; }
    .training-title { font-weight: 800; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .training-body { color: var(--muted); line-height: 1.45; margin-top: 6px; overflow-wrap: anywhere; word-break: break-word; }
    .training-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 9px; }
    .files-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .file-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .file-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .file-kpi .label { color: var(--muted); font-size: 12px; }
    .file-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .file-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .file-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .file-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .file-main > * { min-width: 0; }
    .file-side { display: grid; gap: 14px; }
    .file-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .file-list, .file-path-list, .file-state-list { display: grid; gap: 8px; }
    .file-card { display: grid; grid-template-columns: 142px 104px minmax(0, 1fr); gap: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; border-left: 4px solid #9aa4b2; }
    .file-card > * { min-width: 0; }
    .file-card.analysis { border-left-color: var(--ok); }
    .file-card.filesystem { border-left-color: var(--info); }
    .file-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .file-title { font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .file-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .file-body { color: var(--muted); margin-top: 5px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }
    .file-path-row, .file-state-row { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .file-path-title, .file-state-title { font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .file-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .file-chip { display: inline-flex; align-items: center; border: 1px solid var(--line); border-radius: 999px; padding: 4px 8px; background: #f6f7f9; font-size: 12px; color: #374151; }
    .file-config-list { display: grid; gap: 8px; }
    .recycle-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .recycle-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .recycle-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .recycle-kpi .label { color: var(--muted); font-size: 12px; }
    .recycle-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .recycle-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .recycle-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .recycle-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .recycle-main > * { min-width: 0; }
    .recycle-side { display: grid; gap: 14px; }
    .recycle-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .recycle-list, .recycle-preview-list, .recycle-form, .recycle-category-list { display: grid; gap: 8px; }
    .recycle-card { display: grid; grid-template-columns: 132px 96px minmax(0, 1fr) auto; gap: 10px; border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .recycle-card > * { min-width: 0; }
    .recycle-card.due { border-left-color: var(--warn); }
    .recycle-card.missing { border-left-color: var(--fail); }
    .recycle-card.unknown { border-left-color: #9aa4b2; }
    .recycle-card .btn { align-self: center; white-space: nowrap; }
    .recycle-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .recycle-title { font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .recycle-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .recycle-path { color: var(--muted); margin-top: 5px; line-height: 1.4; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .recycle-preview-row, .recycle-category-row { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .recycle-preview-row:last-child, .recycle-category-row:last-child { border-bottom: 0; }
    .recycle-form input { width: 100%; }
    .recycle-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .recycle-actions .btn { width: 100%; }
    .mobile-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .mobile-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .mobile-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .mobile-kpi .label { color: var(--muted); font-size: 12px; }
    .mobile-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .mobile-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .mobile-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .mobile-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .mobile-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .mobile-main > * { min-width: 0; }
    .mobile-side { display: grid; gap: 14px; }
    .mobile-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .mobile-event-list, .mobile-health-list, .mobile-storage-list, .mobile-cleanup-list, .mobile-config-list, .mobile-failure-list { display: grid; gap: 8px; }
    .mobile-event-card { display: grid; grid-template-columns: 142px 96px minmax(0, 1fr); gap: 10px; border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .mobile-event-card > * { min-width: 0; }
    .mobile-event-card.audio { border-left-color: var(--info); }
    .mobile-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .mobile-title { font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .mobile-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .mobile-row { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .mobile-row:last-child { border-bottom: 0; }
    .mobile-audio-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
    .mobile-audio-stat { border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: #fbfcfe; }
    .mobile-audio-stat .label { color: var(--muted); font-size: 12px; }
    .mobile-audio-stat .value { font-weight: 750; margin-top: 3px; }
    .mobile-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .mobile-actions .btn { width: 100%; }
    .sync-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .sync-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .sync-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .sync-kpi .label { color: var(--muted); font-size: 12px; }
    .sync-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .sync-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .sync-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .sync-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .sync-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .sync-main > * { min-width: 0; }
    .sync-side { display: grid; gap: 14px; }
    .sync-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .sync-event-list, .sync-health-list, .sync-storage-list, .sync-cleanup-list, .sync-config-list { display: grid; gap: 8px; }
    .sync-event-card { display: grid; grid-template-columns: 142px 100px minmax(0, 1fr); gap: 10px; border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .sync-event-card > * { min-width: 0; }
    .sync-event-card.audio { border-left-color: var(--info); }
    .sync-event-card.watch { border-left-color: var(--accent-2); }
    .sync-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .sync-title { font-weight: 750; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .sync-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; }
    .sync-body { color: var(--muted); margin-top: 5px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
    .sync-row { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .sync-row:last-child { border-bottom: 0; }
    .sync-storage-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 10px; }
    .sync-storage-tile { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .sync-storage-tile .label { color: var(--muted); font-size: 12px; }
    .sync-storage-tile .value { font-size: 20px; font-weight: 750; margin-top: 4px; }
    .sync-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .sync-actions .btn { width: 100%; }
    .setup-hero { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 14px; align-items: stretch; }
    .setup-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .setup-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .setup-kpi .label { color: var(--muted); font-size: 12px; }
    .setup-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .setup-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; overflow-wrap: anywhere; word-break: break-word; }
    .setup-main { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 14px; align-items: start; margin-top: 14px; }
    .setup-main > * { min-width: 0; }
    .setup-stack, .setup-side, .setup-step-list, .setup-service-list, .setup-url-list, .setup-copy-list { display: grid; gap: 10px; }
    .setup-step, .setup-service, .setup-url-row, .setup-copy-row { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .setup-step, .setup-service { display: grid; grid-template-columns: 92px minmax(0, 1fr) auto; gap: 10px; align-items: start; }
    .setup-title { font-weight: 800; line-height: 1.3; overflow-wrap: anywhere; }
    .setup-detail { color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 3px; overflow-wrap: anywhere; word-break: break-word; }
    .setup-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .setup-actions .btn { width: 100%; text-align: left; }
    .setup-url-row { display: grid; grid-template-columns: 112px minmax(0, 1fr) auto; gap: 10px; align-items: center; }
    .setup-url { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; word-break: break-word; }
    .setup-token-box { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #f8fafc; display: grid; gap: 8px; }
    .setup-token-value { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .setup-progress { height: 10px; background: #e5e7eb; border-radius: 999px; overflow: hidden; margin-top: 12px; }
    .setup-progress span { display: block; height: 100%; background: var(--accent-2); }
    .settings-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; }
    .settings-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .settings-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .settings-kpi .label { color: var(--muted); font-size: 12px; }
    .settings-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .settings-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-main { display: grid; grid-template-columns: minmax(0, 1fr) 380px; gap: 14px; align-items: start; margin-top: 14px; }
    .settings-main > * { min-width: 0; }
    .settings-side { display: grid; gap: 14px; }
    .settings-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto; gap: 8px; align-items: center; margin-bottom: 10px; }
    .settings-group-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; max-height: min(620px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .settings-group-card { font: inherit; color: var(--text); text-align: left; cursor: pointer; border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; display: grid; gap: 7px; }
    .settings-group-card:hover, .settings-group-card.active { border-color: var(--accent); background: #e9f0ff; }
    .settings-group-card.ok { border-left-color: var(--ok); }
    .settings-group-card.warn { border-left-color: var(--warn); }
    .settings-group-card.disabled { border-left-color: #94a3b8; }
    .settings-group-card[hidden] { display: none; }
    .settings-group-head { display: flex; align-items: center; justify-content: space-between; gap: 8px; min-width: 0; }
    .settings-group-title { font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .settings-group-summary { color: var(--muted); font-size: 13px; line-height: 1.42; overflow-wrap: anywhere; word-break: break-word; }
    .settings-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
    .settings-chip { border: 1px solid var(--line); border-radius: 999px; padding: 4px 9px; background: #f8fafc; color: var(--muted); font-size: 12px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .settings-action-grid .btn { width: 100%; text-align: left; }
    .settings-row-list { display: grid; gap: 0; }
    .settings-row { display: grid; grid-template-columns: 136px minmax(0, 1fr); gap: 10px; border-bottom: 1px solid var(--line); padding: 9px 0; min-width: 0; }
    .settings-row:last-child { border-bottom: 0; }
    .settings-row .label { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-row .value { font-weight: 650; overflow-wrap: anywhere; word-break: break-word; }
    .settings-edit-list { display: grid; gap: 10px; max-height: min(560px, calc(100vh - 260px)); overflow: auto; padding-right: 2px; }
    .settings-edit-row { display: grid; grid-template-columns: 154px minmax(0, 1fr); gap: 10px; align-items: start; border-bottom: 1px solid var(--line); padding: 10px 0; min-width: 0; }
    .settings-edit-row:last-child { border-bottom: 0; }
    .settings-edit-label { display: grid; gap: 3px; min-width: 0; }
    .settings-edit-label b { font-size: 13px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-edit-label span { color: var(--muted); font-size: 12px; overflow-wrap: anywhere; word-break: break-word; }
    .settings-edit-control { min-width: 0; }
    .settings-edit-control input:not([type="checkbox"]), .settings-edit-control select, .settings-edit-control textarea { width: 100%; }
    .settings-edit-toggle { display: inline-flex; align-items: center; gap: 8px; min-height: 38px; font-weight: 700; }
    .settings-edit-toggle input { width: 18px; height: 18px; }
    .settings-edit-actions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: flex-end; margin-top: 12px; }
    .settings-edit-note { color: var(--muted); font-size: 12px; line-height: 1.45; margin-top: 8px; }
    .settings-detail-summary { color: var(--muted); line-height: 1.45; margin: -2px 0 8px; }
    .settings-json { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 9px; }
    .settings-json summary { cursor: pointer; color: var(--muted); font-size: 13px; }
    .settings-pre { max-height: 320px; overflow: auto; margin: 9px 0 0; border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #f8fafc; white-space: pre-wrap; word-break: break-word; font-size: 12px; }
    .compact-details { border-top: 1px solid var(--line); padding-top: 10px; }
    .compact-details summary { cursor: pointer; color: var(--muted); font-size: 13px; font-weight: 750; }
    .compact-details-body { margin-top: 10px; display: grid; gap: 8px; }
    .maintenance-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; }
    .maintenance-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .maintenance-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .maintenance-kpi .label { color: var(--muted); font-size: 12px; }
    .maintenance-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .maintenance-kpi .value.compact { font-size: 20px; line-height: 1.15; }
    .maintenance-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; overflow-wrap: anywhere; word-break: break-word; }
    .maintenance-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .maintenance-main > * { min-width: 0; }
    .maintenance-side { display: grid; gap: 14px; }
    .maintenance-action-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .maintenance-action-grid .btn { width: 100%; text-align: left; }
    .maintenance-list, .maintenance-source-list, .maintenance-log-list { display: grid; gap: 8px; }
    .maintenance-line { display: flex; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .maintenance-line:last-child { border-bottom: 0; }
    .maintenance-source-row, .maintenance-log-row { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; min-width: 0; }
    .maintenance-source-title, .maintenance-log-title { font-weight: 750; overflow-wrap: anywhere; word-break: break-word; }
    .day-toolbar { display: grid; grid-template-columns: 160px 120px 120px minmax(220px, 1fr) auto; gap: 8px; align-items: center; }
    .today-controls { display: grid; gap: 10px; }
    .quickbar { display: flex; flex-wrap: wrap; gap: 8px; }
    .filter-pill {
      border: 1px solid var(--line);
      background: var(--panel-2);
      color: var(--text);
      border-radius: 999px;
      padding: 7px 11px;
      cursor: pointer;
      font-size: 13px;
    }
    .filter-pill:hover, .filter-pill.active { border-color: var(--accent); background: #e9f0ff; color: var(--accent); }
    .today-summary { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(280px, .65fr); gap: 14px; margin-top: 14px; align-items: stretch; }
    .today-stats { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .today-stat { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .today-stat .value { font-size: 24px; font-weight: 750; margin-top: 4px; }
    .today-stat .label { color: var(--muted); font-size: 12px; }
    .today-stat .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .hour-bars { display: grid; grid-template-columns: repeat(24, minmax(4px, 1fr)); gap: 3px; align-items: end; height: 48px; margin-top: 16px; }
    .hour-bar { min-height: 5px; border-radius: 5px 5px 2px 2px; background: var(--accent); opacity: .15; }
    .hour-axis { display: flex; justify-content: space-between; color: var(--muted); font-size: 11px; margin-top: 6px; }
    .category-strip { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .category-chip { display: inline-flex; gap: 7px; align-items: center; }
    .chip-count { color: var(--muted); font-variant-numeric: tabular-nums; }
    .overview-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .overview-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .overview-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .overview-kpi .label { color: var(--muted); font-size: 12px; }
    .overview-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .overview-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .overview-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .overview-main > * { min-width: 0; }
    .overview-side { display: grid; gap: 14px; }
    .overview-health { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; margin-top: 12px; }
    .health-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 9px 10px; background: #fbfcfe; }
    .overview-actions { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
    .overview-actions .btn { width: 100%; text-align: left; }
    .overview-queue { display: grid; gap: 8px; }
    .queue-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 9px 0; }
    .queue-row:last-child { border-bottom: 0; }
    .queue-value { font-weight: 750; }
    .doctor-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .doctor-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .doctor-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .doctor-kpi .label { color: var(--muted); font-size: 12px; }
    .doctor-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .doctor-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .doctor-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .doctor-main > * { min-width: 0; }
    .doctor-side { display: grid; gap: 14px; }
    .doctor-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .issue-list, .check-list, .fix-list, .area-list { display: grid; gap: 8px; }
    .issue-item, .check-row, .fix-item, .area-row { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .issue-item { border-left: 4px solid var(--warn); }
    .issue-item.fail { border-left-color: var(--fail); }
    .issue-item.warn { border-left-color: var(--warn); }
    .check-row { display: grid; grid-template-columns: 74px 120px minmax(0, 1fr); gap: 10px; align-items: start; }
    .check-title { font-weight: 700; line-height: 1.35; }
    .check-message, .fix-command { color: var(--muted); margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; }
    .fix-command { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; color: var(--text); }
    .area-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; cursor: pointer; }
    .area-row.active { border-color: var(--accent); background: #e9f0ff; }
    .area-counts { display: inline-flex; flex-wrap: wrap; justify-content: flex-end; gap: 4px; color: var(--muted); font-size: 12px; }
    .audio-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; }
    .audio-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 14px; }
    .audio-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: #fbfcfe; min-width: 0; }
    .audio-kpi .label { color: var(--muted); font-size: 12px; }
    .audio-kpi .value { font-size: 25px; font-weight: 750; margin-top: 5px; }
    .audio-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .audio-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .audio-main > * { min-width: 0; }
    .audio-side { display: grid; gap: 14px; }
    .audio-filters { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .audio-list, .audio-priority, .status-breakdown { display: grid; gap: 8px; }
    .audio-card { display: grid; grid-template-columns: 150px 112px minmax(0, 1fr); gap: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .audio-card > * { min-width: 0; }
    .audio-card.error, .audio-card.pending, .audio-card.missing_file { border-left: 4px solid var(--warn); }
    .audio-card.error { border-left-color: var(--fail); }
    .audio-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; }
    .audio-title { font-weight: 700; line-height: 1.35; }
    .audio-body { color: var(--muted); margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; display: -webkit-box; -webkit-line-clamp: 4; -webkit-box-orient: vertical; overflow: hidden; }
    .audio-list .audio-body { -webkit-line-clamp: 3; }
    .audio-path { color: var(--muted); font-size: 12px; margin-top: 5px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; word-break: break-word; }
    .status-row { display: flex; align-items: center; justify-content: space-between; gap: 10px; border-bottom: 1px solid var(--line); padding: 9px 0; }
    .status-row:last-child { border-bottom: 0; }
    .action-hero { display: grid; grid-template-columns: minmax(0, 1.2fr) minmax(320px, .8fr); gap: 14px; align-items: stretch; margin-top: 14px; }
    .action-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: var(--panel); }
    .action-kpi { padding: 14px; border-right: 1px solid var(--line); min-width: 0; }
    .action-kpi:last-child { border-right: 0; }
    .action-kpi .value { font-size: 26px; font-weight: 800; line-height: 1.1; overflow-wrap: anywhere; }
    .action-toolbar { display: grid; grid-template-columns: minmax(0, 1fr); gap: 8px; align-items: center; }
    .action-toolbar input { width: 100%; min-width: 0; }
    .action-main { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(320px, .75fr); gap: 14px; align-items: start; margin-top: 14px; }
    .action-stack, .action-side { display: grid; gap: 14px; min-width: 0; }
    .repair-list, .suggestion-list, .project-list, .quality-list, .quick-tag-list, .highlight-list { display: grid; gap: 8px; }
    .repair-card, .suggestion-card, .project-card, .quality-card, .quick-tag-card, .highlight-card { border: 1px solid var(--line); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .repair-card.critical { border-left: 4px solid var(--fail); }
    .repair-card.warn { border-left: 4px solid var(--warn); }
    .repair-card.info { border-left: 4px solid #64748b; }
    .repair-top, .suggestion-top, .project-top, .quality-top, .highlight-top { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; min-width: 0; }
    .repair-title, .suggestion-title, .project-title, .quality-title, .highlight-title { font-weight: 800; line-height: 1.35; overflow-wrap: anywhere; }
    .repair-body, .suggestion-body, .project-body, .quality-body, .highlight-body { color: var(--muted); line-height: 1.45; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .repair-evidence, .project-evidence, .quality-issues { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; min-width: 0; }
    .evidence-chip { display: inline-flex; max-width: 100%; border: 1px solid var(--line); border-radius: 999px; padding: 3px 8px; color: var(--muted); font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
    .project-keywords, .quick-tag-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; }
    .quality-meter { height: 8px; background: #e5e7eb; border-radius: 999px; overflow: hidden; margin-top: 8px; }
    .quality-meter span { display: block; height: 100%; background: #2f7d57; }
    .quality-meter.weak span { background: var(--fail); }
    .quality-meter.needs_work span { background: var(--warn); }
    .evidence-groups { display: grid; gap: 10px; }
    .evidence-group { border: 1px solid var(--line); border-radius: 8px; padding: 10px; background: #fbfcfe; }
    .evidence-item { border-top: 1px solid var(--line); padding-top: 8px; margin-top: 8px; }
    .insight-hero { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: stretch; margin-top: 14px; }
    .insight-toolbar { display: grid; grid-template-columns: 142px minmax(180px, 1fr) 150px 150px auto; gap: 8px; align-items: center; }
    .insight-toolbar.projects { grid-template-columns: 142px minmax(180px, 1fr) 150px 150px auto; }
    .insight-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 10px; margin-top: 12px; }
    .insight-kpi { border: 1px solid var(--line); border-radius: 8px; padding: 11px; background: #fbfcfe; min-width: 0; }
    .insight-kpi .label { color: var(--muted); font-size: 12px; }
    .insight-kpi .value { font-size: 24px; font-weight: 800; margin-top: 4px; overflow-wrap: anywhere; }
    .insight-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 3px; }
    .insight-main { display: grid; grid-template-columns: minmax(0, 1fr) 360px; gap: 14px; align-items: start; margin-top: 14px; }
    .insight-main > * { min-width: 0; }
    .insight-side { display: grid; gap: 14px; }
    .insight-list { display: grid; gap: 9px; max-height: min(760px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .insight-card { border: 1px solid var(--line); border-left: 4px solid var(--accent); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .insight-card.high { border-left-color: var(--fail); }
    .insight-card.medium { border-left-color: var(--warn); }
    .insight-card.project { border-left-color: var(--accent-2); }
    .insight-card.repair { border-left-color: var(--warn); }
    .insight-card.quick_tag { border-left-color: var(--accent); }
    .insight-card.speaker { border-left-color: #64748b; }
    .insight-card.done, .insight-card.archived, .insight-card.dismissed { opacity: .72; }
    .insight-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; min-width: 0; }
    .insight-title { font-weight: 800; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .insight-body { color: var(--muted); line-height: 1.5; margin-top: 7px; overflow-wrap: anywhere; word-break: break-word; }
    .insight-chips, .insight-actions { display: flex; flex-wrap: wrap; gap: 7px; margin-top: 9px; }
    .insight-actions .btn { min-width: 92px; }
    .insight-note { display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 8px; margin-top: 9px; align-items: start; }
    .insight-note textarea { min-height: 52px; }
    .insight-evidence { margin-top: 10px; border-top: 1px solid var(--line); padding-top: 8px; }
    .insight-evidence summary { cursor: pointer; color: var(--muted); font-weight: 750; font-size: 13px; }
    .insight-evidence-list { display: grid; gap: 8px; margin-top: 8px; }
    .insight-evidence-row { border: 1px solid var(--line); border-radius: 8px; padding: 9px; background: #fbfcfe; min-width: 0; }
    .insight-evidence-row b { overflow-wrap: anywhere; word-break: break-word; }
    .insight-state-list, .insight-breakdown { display: grid; gap: 8px; }
    .insight-state-row { display: flex; justify-content: space-between; align-items: center; gap: 10px; border-bottom: 1px solid var(--line); padding: 8px 0; }
    .insight-state-row:last-child { border-bottom: 0; }
    .inbox-toolbar { grid-template-columns: 128px minmax(180px, 1fr) 140px 140px 140px auto; }
    .memory-list, .meeting-list, .meeting-note-list { display: grid; gap: 9px; }
    .memory-card, .meeting-card { border: 1px solid var(--line); border-left: 4px solid var(--accent-2); border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .memory-card.focused { border-left-color: var(--accent); }
    .memory-card.archived, .meeting-card.ended { border-left-color: #9aa4b2; opacity: .82; }
    .memory-head, .meeting-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 10px; min-width: 0; }
    .memory-title, .meeting-title { font-weight: 800; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .memory-body, .meeting-body { color: var(--muted); line-height: 1.5; margin-top: 7px; overflow-wrap: anywhere; word-break: break-word; }
    .memory-actions, .meeting-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 9px; }
    .meeting-active { border-left-color: var(--accent); background: #fbfcfe; }
    .privacy-hero, .privacy-main { display: grid; grid-template-columns: minmax(0, 1.35fr) minmax(320px, .65fr); gap: 14px; align-items: start; margin-bottom: 14px; }
    .privacy-kpis { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; background: #fbfcfe; }
    .privacy-kpi { padding: 12px; border-right: 1px solid var(--line); min-width: 0; }
    .privacy-kpi:last-child { border-right: 0; }
    .privacy-kpi .label { color: var(--muted); font-size: 12px; font-weight: 700; }
    .privacy-kpi .value { font-size: 24px; font-weight: 850; margin-top: 4px; overflow-wrap: anywhere; word-break: break-word; }
    .privacy-kpi .hint { color: var(--muted); font-size: 12px; margin-top: 4px; overflow-wrap: anywhere; word-break: break-word; }
    .privacy-toolbar { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
    .privacy-source-list, .privacy-check-list, .privacy-storage-list { display: grid; gap: 9px; max-height: min(660px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .privacy-source-card { border: 1px solid var(--line); border-left: 4px solid #9aa4b2; border-radius: 8px; padding: 12px; background: var(--panel); min-width: 0; }
    .privacy-source-card.high { border-left-color: #c2410c; }
    .privacy-source-card.medium { border-left-color: #b7791f; }
    .privacy-source-card.low { border-left-color: #2f855a; }
    .privacy-source-card.disabled { opacity: .78; }
    .privacy-row-head, .privacy-check-row, .privacy-storage-row { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; min-width: 0; }
    .privacy-title { font-weight: 800; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .privacy-note { color: var(--muted); line-height: 1.45; margin-top: 5px; overflow-wrap: anywhere; word-break: break-word; }
    .privacy-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 10px; }
    .privacy-check-row, .privacy-storage-row { border-bottom: 1px solid var(--line); padding: 9px 0; }
    .privacy-check-row:last-child, .privacy-storage-row:last-child { border-bottom: 0; }
    .evidence-item:first-of-type { border-top: 0; padding-top: 0; margin-top: 0; }
    .today-main { display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 14px; align-items: start; margin-top: 14px; width: 100%; min-width: 0; max-width: 100%; overflow-x: hidden; }
    .today-main > *, .today-sidebar, .day-list, .day-section { min-width: 0; }
    .today-sidebar { display: grid; gap: 14px; position: sticky; top: 24px; }
    .day-section { display: grid; gap: 8px; margin-bottom: 16px; }
    .day-section-header { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 2px 2px 0; }
    .day-section-header h3 { margin: 0; font-size: 15px; }
    .day-feed { max-height: min(760px, calc(100vh - 220px)); overflow: auto; padding-right: 2px; }
    .day-list { display: grid; gap: 8px; }
    .day-event { display: grid; grid-template-columns: 74px 104px minmax(0, 1fr); gap: 10px; padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--panel); max-width: 100%; overflow: hidden; }
    .day-event > * { min-width: 0; }
    .day-event:hover { border-color: #aeb8c9; }
    .event-time { color: var(--muted); font-size: 12px; font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; overflow-wrap: anywhere; word-break: break-word; }
    .event-title { font-weight: 700; line-height: 1.35; overflow-wrap: anywhere; word-break: break-word; }
    .event-body { color: var(--muted); margin-top: 4px; line-height: 1.45; overflow-wrap: anywhere; word-break: break-word; }
    .event-meta { display: flex; flex-wrap: wrap; gap: 4px 10px; color: var(--muted); font-size: 12px; margin-top: 4px; min-width: 0; max-width: 100%; overflow-wrap: anywhere; word-break: break-word; }
    .event-meta span { min-width: 0; max-width: 100%; overflow-wrap: anywhere; word-break: break-word; }
    .empty-state { border: 1px dashed var(--line); border-radius: 8px; padding: 18px; color: var(--muted); background: #fbfcfe; }
    .category { display: inline-flex; align-items: center; width: fit-content; border-radius: 999px; padding: 4px 9px; font-size: 12px; font-weight: 700; background: #edf2f7; color: #1f2937; }
    .category.audio { background:#e5eefb; color:#225a9b; }
    .category.app { background:#e8f4ef; color:#127a4a; }
    .category.chat { background:#f3e8ff; color:#6d28d9; }
    .category.file { background:#fff1d6; color:#a85f00; }
    .category.location { background:#e0f2fe; color:#075985; }
    .category.reminder, .category.calendar { background:#fde7e5; color:#b3261e; }
    .feedback-row { border-bottom: 1px solid var(--line); padding: 9px 0; }
    .feedback-row:last-child { border-bottom: 0; }
    .has-tip { position: relative; }
    .button-tooltip {
      position: fixed;
      display: none;
      max-width: min(340px, calc(100vw - 24px));
      padding: 8px 10px;
      border-radius: 8px;
      background: #111827;
      color: #fff;
      font-size: 12px;
      line-height: 1.45;
      box-shadow: var(--shadow);
      pointer-events: none;
      z-index: 30;
    }
    .button-tooltip.show { display: block; }
    .toast { position: fixed; right: 18px; bottom: 18px; background: #111827; color: #fff; padding: 12px 14px; border-radius: 8px; max-width: 560px; box-shadow: var(--shadow); display: none; white-space: pre-wrap; z-index: 10; }
    .toast.show { display: block; }
    .section-title { display:flex; justify-content:space-between; align-items:center; gap:10px; margin-bottom:10px; }
    .section-title h3 { margin:0; font-size:16px; }
    .repair-body, .suggestion-body, .project-body, .quality-issues, .highlight-body, .source-issue-body, .check-message {
      display: -webkit-box;
      -webkit-box-orient: vertical;
      -webkit-line-clamp: 4;
      overflow: hidden;
    }
    .project-body, .highlight-body, .source-issue-body, .check-message { -webkit-line-clamp: 3; }
    .repair-list, .suggestion-list, .project-list, .quality-list, .highlight-list, .issue-list, .fix-list, .area-list, .speaker-grid, .speaker-match-list, .speaker-sample-list, .audio-list, .file-list, .sync-event-list, .source-grid, .reports-list, .check-list {
      max-height: min(620px, calc(100vh - 220px));
      overflow: auto;
      padding-right: 2px;
    }
    .speaker-sample-list { max-height: 520px; }
    .speaker-match-list { max-height: 360px; }
    @media (max-width: 1080px) {
      .app { grid-template-columns: 1fr; }
      aside { position: static; height: auto; }
      nav { grid-template-columns: repeat(2, minmax(0,1fr)); }
      .grid.cols-4, .grid.cols-3, .grid.cols-2, .split, .reports-layout, .reports-metrics, .day-layout, .day-toolbar, .today-summary, .today-main, .today-stats, .action-hero, .action-main, .action-kpis, .action-toolbar, .insight-hero, .insight-main, .insight-kpis, .insight-toolbar, .inbox-toolbar, .overview-hero, .overview-main, .overview-kpis, .doctor-hero, .doctor-main, .doctor-kpis, .check-row, .audio-hero, .audio-main, .audio-kpis, .audio-card, .searchbar, .search-hero, .search-main, .search-answer-layout, .search-retrieval, .search-index-grid, .search-metric-grid, .timeline-hero, .timeline-toolbar, .timeline-stats, .timeline-main, .timeline-event, .sources-hero, .source-kpis, .source-action-grid, .sources-main, .source-grid, .source-kind-row, .speakers-hero, .speaker-command-row, .speaker-filter-row, .speaker-review-toolbar, .speaker-sample-toolbar, .speaker-selection-grid, .speaker-bulk-actions, .speaker-bulk-row, .speaker-tool-row, .speakers-main, .speaker-grid, .files-hero, .file-kpis, .file-main, .file-toolbar, .file-card, .recycle-hero, .recycle-kpis, .recycle-main, .recycle-toolbar, .recycle-card, .recycle-actions, .mobile-hero, .mobile-kpis, .mobile-main, .mobile-toolbar, .mobile-event-card, .mobile-audio-grid, .mobile-actions, .sync-hero, .sync-kpis, .sync-main, .sync-toolbar, .sync-event-card, .sync-storage-grid, .sync-actions, .setup-hero, .setup-kpis, .setup-main, .setup-step, .setup-service, .setup-url-row, .privacy-hero, .privacy-main, .privacy-kpis, .settings-hero, .settings-kpis, .settings-main, .settings-toolbar, .settings-group-grid, .settings-action-grid, .settings-row, .settings-edit-row, .maintenance-hero, .maintenance-kpis, .maintenance-main, .maintenance-action-grid { grid-template-columns: 1fr; }
      .today-stats, .timeline-stats, .overview-kpis, .doctor-kpis, .audio-kpis, .source-kpis, .file-kpis, .sync-kpis, .setup-kpis, .privacy-kpis, .settings-kpis, .maintenance-kpis, .action-kpis, .insight-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .action-kpi { border-right: 1px solid var(--line); border-bottom: 1px solid var(--line); }
      .action-kpi:nth-child(2n) { border-right: 0; }
      .action-kpi:nth-last-child(-n+2) { border-bottom: 0; }
      .speaker-kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .speaker-kpi:nth-child(2n) { border-right: 0; }
      .speaker-kpi:nth-child(-n+2) { border-bottom: 1px solid var(--line); }
      .searchbar { grid-template-columns: 1fr; }
      .day-event { grid-template-columns: 1fr; }
      .today-sidebar { position: static; }
      .overview-health, .overview-actions { grid-template-columns: 1fr; }
      .training-hero, .training-main, .training-kpis, .training-stage-grid { grid-template-columns: 1fr; }
      .training-kpis, .training-stage-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .reports-side { position: static; }
    }
    @media (max-width: 720px) {
      main { padding: 14px; }
      aside { padding: 12px; }
      nav { grid-template-columns: 1fr; gap: 8px; }
      .brand { padding-bottom: 10px; }
      .topbar { display: grid; gap: 12px; margin-bottom: 12px; }
      h2 { font-size: 23px; }
      .toolbar { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); width: 100%; }
      .toolbar .section-tabs { grid-column: 1 / -1; margin-right: 0; }
      .toolbar .btn { width: 100%; }
      .card { padding: 12px; }
      .section-title { align-items: flex-start; flex-wrap: wrap; }
      .section-title h3 { font-size: 15px; }
      .filter-pill { padding: 6px 9px; }
      .reports-layout { display: grid; }
      .report-reader { order: -1; min-height: 0; }
      .reports-nav { order: 0; }
      .reports-side { order: 1; }
      .day-feed, .timeline-feed, .repair-list, .suggestion-list, .project-list, .quality-list, .highlight-list, .insight-list, .action-inbox-list, .memory-list, .meeting-list, .privacy-source-list, .privacy-check-list, .privacy-storage-list, .issue-list, .fix-list, .area-list, .speaker-grid, .speaker-match-list, .speaker-sample-list, .audio-list, .file-list, .sync-event-list, .source-grid, .reports-list, .check-list, .report-reader-content, .settings-group-grid, .settings-edit-list {
        max-height: 460px;
      }
      .training-list, .training-sample-list, .training-match-list { max-height: 460px; }
      .training-kpis, .training-stage-grid { grid-template-columns: 1fr; }
      .speaker-match-list { max-height: 320px; }
      .timeline-breakdown { max-height: 300px; }
    }
  </style>
</head>
<body>
<div class="app">
  <aside>
    <div class="brand"><div class="mark"></div><div><h1>Wond</h1><span>Local control center</span></div></div>
    <nav id="nav"></nav>
  </aside>
  <main>
    <div class="topbar">
      <div><h2 id="title">Overview</h2><div id="subtitle" class="subtitle"></div></div>
      <div class="toolbar" id="toolbar"></div>
    </div>
    <div id="view"></div>
  </main>
</div>
<div id="toast" class="toast"></div>
<div id="buttonTooltip" class="button-tooltip" role="tooltip"></div>
<script>
const sections = [
  ['today','今天'], ['action','行动'], ['search','资料'], ['audio','音频'], ['setup','系统']
];
const childSections = [
  ['inbox','处理队列'], ['projects','项目聚类'], ['memory','项目记忆'], ['personal','个人档案'], ['meeting','会议'],
  ['speaker-training','Speaker 训练'], ['speakers','说话人'],
  ['files','文件'], ['sources','来源'], ['reports','报告'],
  ['privacy','隐私与保留'], ['sync','手机同步'], ['doctor','诊断'], ['settings','配置']
];
const utilitySections = [
  ['overview','总览'], ['timeline','时间线'], ['recycle','回收箱'], ['maintenance','记录维护']
];
const allSections = [...sections, ...childSections, ...utilitySections];
const languageStorageKey = 'wond.dashboard.language';
const supportedLanguages = [
  ['en', 'English'],
  ['zh', '中文'],
  ['ja', '日本語'],
  ['ko', '한국어']
];
function normalizeLanguage(value){
  const lang = String(value || '').toLowerCase();
  return supportedLanguages.some(([code]) => code === lang) ? lang : 'en';
}
function readLanguagePreference(){
  try { return normalizeLanguage(localStorage.getItem(languageStorageKey) || 'en'); }
  catch { return 'en'; }
}
let activeLanguage = readLanguagePreference();
const translationRows = [
  ['总览','Overview','概要','개요'],
  ['今天','Today','今日','오늘'],
  ['昨天','Yesterday','昨日','어제'],
  ['行动','Action','アクション','작업'],
  ['资料','Knowledge','資料','자료'],
  ['音频','Audio','音声','오디오'],
  ['系统','System','システム','시스템'],
  ['日常','Daily','日常','일상'],
  ['记忆','Memory','記憶','기억'],
  ['处理队列','Inbox','処理キュー','처리 대기열'],
  ['项目聚类','Projects','プロジェクトクラスタ','프로젝트 클러스터'],
  ['项目记忆','Project Memory','プロジェクト記憶','프로젝트 기억'],
  ['个人档案','Personal Profile','個人プロファイル','개인 프로필'],
  ['个人记忆','Personal Memory','個人記憶','개인 기억'],
  ['记忆收件箱','Memory Inbox','記憶インボックス','기억 받은함'],
  ['联系人档案','People Files','人物ファイル','인물 파일'],
  ['冲突队列','Conflict Queue','競合キュー','충돌 대기열'],
  ['确认记忆','Confirmed Memories','確認済み記憶','확인된 기억'],
  ['快速写入','Quick Add','クイック追加','빠른 추가'],
  ['档案字段','Profile Fields','プロファイル項目','프로필 필드'],
  ['候选提取','Candidate Extraction','候補抽出','후보 추출'],
  ['隐私与删除','Privacy & Delete','プライバシーと削除','개인정보 및 삭제'],
  ['彻底删除','Delete Permanently','完全に削除','영구 삭제'],
  ['会议','Meeting','ミーティング','회의'],
  ['Speaker 训练','Speaker Training','話者トレーニング','화자 훈련'],
  ['Speaker 训练闭环','Speaker Training Loop','話者トレーニングループ','화자 훈련 루프'],
  ['说话人','Speakers','話者','화자'],
  ['文件','Files','ファイル','파일'],
  ['来源','Sources','ソース','소스'],
  ['报告','Reports','レポート','보고서'],
  ['隐私与保留','Privacy & Retention','プライバシーと保持','개인정보 및 보존'],
  ['手机同步','Mobile Sync','モバイル同期','모바일 동기화'],
  ['诊断','Doctor','診断','진단'],
  ['配置','Settings','設定','설정'],
  ['时间线','Timeline','タイムライン','타임라인'],
  ['回收箱','Recycle Bin','ごみ箱','휴지통'],
  ['记录维护','Maintenance','記録メンテナンス','기록 유지관리'],
  ['日内时间线','Day Timeline','日内タイムライン','일일 타임라인'],
  ['原始记录','Raw Records','生レコード','원본 기록'],
  ['行动总览','Action Overview','アクション概要','작업 개요'],
  ['资料问答','Knowledge Q&A','資料Q&A','자료 Q&A'],
  ['录音队列','Recording Queue','録音キュー','녹음 대기열'],
  ['说话人整理','Speaker Cleanup','話者整理','화자 정리'],
  ['训练闭环','Training Loop','トレーニングループ','훈련 루프'],
  ['启动向导','Setup Guide','セットアップガイド','설정 가이드'],
  ['隐私保留','Privacy Retention','プライバシー保持','개인정보 보존'],
  ['维护','Maintenance','メンテナンス','유지관리'],
  ['系统总览','System Overview','システム概要','시스템 개요'],
  ['全部来源','All sources','すべてのソース','모든 소스'],
  ['全部类型','All types','すべての種類','모든 유형'],
  ['全部优先级','All priorities','すべての優先度','모든 우선순위'],
  ['高优先级','High priority','高優先度','높은 우선순위'],
  ['中优先级','Medium priority','中優先度','중간 우선순위'],
  ['低优先级','Low priority','低優先度','낮은 우선순위'],
  ['全部','All','すべて','전체'],
  ['活跃','Active','アクティブ','활성'],
  ['未处理','Open','未処理','미처리'],
  ['稍后','Snoozed','後で','나중에'],
  ['已完成','Done','完了','완료'],
  ['已忽略','Dismissed','無視済み','무시됨'],
  ['已归档','Archived','アーカイブ済み','보관됨'],
  ['置顶','Pinned','ピン留め','고정됨'],
  ['建议','Suggestion','提案','제안'],
  ['快速标注','Quick Tag','クイックタグ','빠른 태그'],
  ['修复','Repair','修復','수정'],
  ['项目','Project','プロジェクト','프로젝트'],
  ['高','High','高','높음'],
  ['中','Medium','中','중간'],
  ['低','Low','低','낮음'],
  ['开启','On','オン','켜짐'],
  ['关闭','Off','オフ','꺼짐'],
  ['启用','Enabled','有効','활성화'],
  ['停用','Disabled','無効','비활성'],
  ['使用中','In use','使用中','사용 중'],
  ['备用','Fallback','予備','대체'],
  ['读取中...','Loading...','読み込み中...','읽는 중...'],
  ['刷新','Refresh','更新','새로고침'],
  ['刷新状态','Refresh status','状態を更新','상태 새로고침'],
  ['刷新今日报告','Refresh today report','今日のレポートを更新','오늘 보고서 새로고침'],
  ['刷新日报','Refresh daily report','日報を更新','일일 보고서 새로고침'],
  ['采集','Collect','収集','수집'],
  ['采集一次','Collect once','一度収集','한 번 수집'],
  ['采集并写报告','Collect and write report','収集してレポート作成','수집 후 보고서 작성'],
  ['分析音频','Analyze audio','音声を分析','오디오 분석'],
  ['分析 5 条','Analyze 5','5件分析','5개 분석'],
  ['分析 10 条','Analyze 10','10件分析','10개 분석'],
  ['分析 20 条','Analyze 20','20件分析','20개 분석'],
  ['分析 50 条','Analyze 50','50件分析','50개 분석'],
  ['手动切分样本','Manual split sample','サンプルを手動分割','샘플 수동 분할'],
  ['分离成新说话人','Detach to new speaker','新しい話者に分離','새 화자로 분리'],
  ['查找','Find','検索','찾기'],
  ['搜索','Search','検索','검색'],
  ['底层时间线','Raw timeline','生タイムライン','원본 타임라인'],
  ['写入长期记忆','Save to memory','長期記憶に保存','장기 기억에 저장'],
  ['生成新 token','Generate new token','新しいtokenを生成','새 token 생성'],
  ['安装全部服务','Install all services','すべてのサービスをインストール','모든 서비스 설치'],
  ['安装同步服务','Install sync service','同期サービスをインストール','동기화 서비스 설치'],
  ['安装采集 Agent','Install collector agent','収集Agentをインストール','수집 Agent 설치'],
  ['安装 Dashboard','Install Dashboard','Dashboardをインストール','Dashboard 설치'],
  ['安装','Install','インストール','설치'],
  ['复制','Copy','コピー','복사'],
  ['复制 token','Copy token','tokenをコピー','token 복사'],
  ['复制 URL','Copy URL','URLをコピー','URL 복사'],
  ['隐藏 token','Hide token','tokenを隠す','token 숨기기'],
  ['打开处理队列','Open inbox','処理キューを開く','처리 대기열 열기'],
  ['执行第一条修复','Run first repair','最初の修復を実行','첫 수정 실행'],
  ['证据问答','Evidence Q&A','証拠Q&A','증거 Q&A'],
  ['今天时间线','Today timeline','今日のタイムライン','오늘 타임라인'],
  ['查看全部','View all','すべて表示','전체 보기'],
  ['当前完成','Mark current done','現在を完了にする','현재 항목 완료'],
  ['当前稍后','Snooze current','現在を後回し','현재 항목 나중에'],
  ['当前忽略','Dismiss current','現在を無視','현재 항목 무시'],
  ['完成','Done','完了','완료'],
  ['取消置顶','Unpin','ピン留め解除','고정 해제'],
  ['问证据','Ask evidence','証拠を質問','증거 질문'],
  ['问项目证据','Ask project evidence','プロジェクト証拠を質問','프로젝트 증거 질문'],
  ['忽略','Dismiss','無視','무시'],
  ['保存备注','Save note','メモを保存','메모 저장'],
  ['关注','Focus','注目','집중'],
  ['取消关注','Unfocus','注目解除','집중 해제'],
  ['归档','Archive','アーカイブ','보관'],
  ['写入项目记忆','Save to project memory','プロジェクト記憶に保存','프로젝트 기억에 저장'],
  ['开会','Start meeting','会議を開始','회의 시작'],
  ['创建记忆','Create memory','記憶を作成','기억 생성'],
  ['开始会议','Start meeting','会議を開始','회의 시작'],
  ['开始会议记录','Start meeting notes','会議メモを開始','회의 기록 시작'],
  ['记录笔记','Add note','メモを記録','메모 기록'],
  ['结束并写入项目记忆','End and save to memory','終了して記憶に保存','종료 후 기억에 저장'],
  ['首次配置进度','Setup progress','初期設定の進捗','초기 설정 진행률'],
  ['完成度','Completion','完了率','완료율'],
  ['快捷操作','Quick actions','クイック操作','빠른 작업'],
  ['检查清单','Checklist','チェックリスト','체크리스트'],
  ['iPhone 连接','iPhone connection','iPhone接続','iPhone 연결'],
  ['Mac 服务','Mac services','Macサービス','Mac 서비스'],
  ['本机路径','Local paths','ローカルパス','로컬 경로'],
  ['同步 Token','Sync token','同期token','동기화 token'],
  ['已配置','Configured','設定済み','설정됨'],
  ['未配置','Not configured','未設定','미설정'],
  ['需要生成','Needs generation','生成が必要','생성 필요'],
  ['本地','Local','ローカル','로컬'],
  ['本地数据库','Local database','ローカルデータベース','로컬 데이터베이스'],
  ['同步服务','Sync service','同期サービス','동기화 서비스'],
  ['后台采集','Background collector','バックグラウンド収集','백그라운드 수집'],
  ['Dashboard 服务','Dashboard service','Dashboardサービス','Dashboard 서비스'],
  ['本机测试','Local test','ローカルテスト','로컬 테스트'],
  ['还没有 token。先生成 token，再把 URL 和 token 填到 iPhone 的 Wond 设置里。','No token yet. Generate one, then enter the URL and token in Wond settings on iPhone.','tokenがまだありません。先にtokenを生成し、URLとtokenをiPhoneのWond設定に入力してください。','아직 token이 없습니다. 먼저 token을 생성한 뒤 iPhone의 Wond 설정에 URL과 token을 입력하세요.'],
  ['已有 token。为了安全，现有 token 不会明文显示；需要配置新手机时可以生成一个新的。','A token exists. For safety, the current token is hidden. Generate a new one when setting up a new phone.','tokenは設定済みです。安全のため現在のtokenは表示されません。新しい端末を設定するときは新規生成できます。','token이 있습니다. 안전을 위해 현재 token은 표시되지 않습니다. 새 휴대폰을 설정할 때 새로 생성할 수 있습니다.'],
  ['运行状态','Runtime status','実行状態','실행 상태'],
  ['待处理','Pending','保留中','대기 중'],
  ['快捷入口','Shortcuts','ショートカット','바로가기'],
  ['运行记录','Run records','実行記録','실행 기록'],
  ['诊断状态','Doctor status','診断状態','진단 상태'],
  ['修复入口','Repair actions','修復入口','수정 작업'],
  ['优先处理','Priority issues','優先対応','우선 처리'],
  ['检查明细','Check details','チェック詳細','검사 상세'],
  ['音频队列','Audio queue','音声キュー','오디오 대기열'],
  ['分类','Categories','カテゴリ','분류'],
  ['事件流','Event stream','イベントストリーム','이벤트 스트림'],
  ['每日反馈','Daily feedback','日次フィードバック','일일 피드백'],
  ['已记录','Recorded','記録済み','기록됨'],
  ['报告库','Report library','レポートライブラリ','보고서 라이브러리'],
  ['当前文件','Current file','現在のファイル','현재 파일'],
  ['大纲','Outline','アウトライン','개요'],
  ['来源总览','Source overview','ソース概要','소스 개요'],
  ['来源动作','Source actions','ソース操作','소스 작업'],
  ['来源明细','Source details','ソース詳細','소스 상세'],
  ['需要处理','Needs work','対応が必要','처리 필요'],
  ['记录分布','Record distribution','記録分布','기록 분포'],
  ['训练状态','Training status','トレーニング状態','훈련 상태'],
  ['训练分数','Training score','トレーニングスコア','훈련 점수'],
  ['稳定身份','Stable identities','安定したID','안정된 신원'],
  ['样本/Embedding','Samples / Embeddings','サンプル / Embedding','샘플 / Embedding'],
  ['代表样本','Representative samples','代表サンプル','대표 샘플'],
  ['闭环阶段','Loop stages','ループ段階','루프 단계'],
  ['Speaker 队列','Speaker queue','話者キュー','화자 대기열'],
  ['样本队列','Sample queue','サンプルキュー','샘플 대기열'],
  ['整理队列','Cleanup queue','整理キュー','정리 대기열'],
  ['样本浏览','Sample browser','サンプル閲覧','샘플 탐색'],
  ['质量中心','Quality center','品質センター','품질 센터'],
  ['下一步','Next step','次のステップ','다음 단계'],
  ['维护工具','Maintenance tools','メンテナンスツール','유지관리 도구'],
  ['危险操作','Danger zone','危険操作','위험 작업'],
  ['人物档案','Speaker profile','人物プロファイル','인물 프로필'],
  ['分析状态','Analysis status','分析状態','분석 상태'],
  ['扫描控制','Scan controls','スキャン制御','스캔 제어'],
  ['最近文件记录','Recent file records','最近のファイル記録','최근 파일 기록'],
  ['监控路径','Watch paths','監視パス','감시 경로'],
  ['格式规则','Format rules','形式ルール','형식 규칙'],
  ['状态文件','State file','状態ファイル','상태 파일'],
  ['清理动作','Cleanup actions','クリーンアップ操作','정리 작업'],
  ['记录体量','Record volume','記録量','기록 용량'],
  ['按保留策略清理记录','Clean records by retention policy','保持ポリシーで記録を整理','보존 정책으로 기록 정리'],
  ['缓存与回收箱','Cache & recycle bin','キャッシュとごみ箱','캐시 및 휴지통'],
  ['增长来源','Growth sources','増加ソース','증가 소스'],
  ['数据库','Database','データベース','데이터베이스'],
  ['日志文件','Log files','ログファイル','로그 파일'],
  ['摘要','Summary','要約','요약'],
  ['主题','Topic','トピック','주제'],
  ['主题聚类','Topic clusters','トピッククラスタ','주제 클러스터'],
  ['今日','Today','今日','오늘'],
  ['今日重点','Today highlights','今日のハイライト','오늘의 핵심'],
  ['今日证据','Today evidence','今日の証拠','오늘 증거'],
  ['快速流转','Quick flow','クイックフロー','빠른 흐름'],
  ['待修复','Needs repair','修復待ち','수정 필요'],
  ['待修复队列','Repair queue','修復キュー','수정 대기열'],
  ['质量','Quality','品質','품질'],
  ['说话人质量','Speaker quality','話者品質','화자 품질'],
  ['可执行','Runnable','実行可能','실행 가능'],
  ['处理队列摘要','Inbox summary','処理キュー要約','처리 대기열 요약'],
  ['项目 / 主题聚类','Projects / Topic clusters','プロジェクト / トピッククラスタ','프로젝트 / 주제 클러스터'],
  ['隐私概览','Privacy overview','プライバシー概要','개인정보 개요'],
  ['快速控制','Quick controls','クイック制御','빠른 제어'],
  ['敏感来源','Sensitive sources','機密ソース','민감 소스'],
  ['保留策略','Retention policy','保持ポリシー','보존 정책'],
  ['清理预览','Cleanup preview','クリーンアッププレビュー','정리 미리보기'],
  ['发布边界','Publication boundary','公開境界','공개 경계'],
  ['数据占用','Storage usage','データ使用量','데이터 사용량'],
  ['配置总览','Settings overview','設定概要','설정 개요'],
  ['配置分组','Setting groups','設定グループ','설정 그룹'],
  ['可编辑设置','Editable settings','編集可能な設定','편집 가능한 설정'],
  ['当前分组详情','Current group details','現在のグループ詳細','현재 그룹 상세'],
  ['路径和安全','Paths & safety','パスと安全性','경로 및 안전'],
  ['维护动作','Maintenance actions','メンテナンス操作','유지관리 작업'],
  ['语言','Language','言語','언어'],
  ['界面语言','Interface language','インターフェース言語','인터페이스 언어'],
  ['语言设置','Language settings','言語設定','언어 설정'],
  ['选择界面语言','Choose interface language','表示言語を選択','인터페이스 언어 선택'],
  ['立即应用','Apply now','今すぐ適用','지금 적용'],
  ['初始语言为英语，切换会保存在此浏览器。','Default is English. Changes are saved in this browser.','初期言語は英語です。変更はこのブラウザに保存されます。','초기 언어는 영어입니다. 변경 사항은 이 브라우저에 저장됩니다.'],
  ['切换会保存在此浏览器，并同步为日报/周报邮件语言。','Changes are saved in this browser and synced as the daily/weekly email language.','変更はこのブラウザに保存され、日報/週報メールの言語として同期されます。','변경 사항은 이 브라우저에 저장되며 일일/주간 이메일 언어로 동기화됩니다.'],
  ['界面语言，也会作为日报和周报邮件的输出语言。','Interface language; also used as the output language for daily and weekly emails.','インターフェース言語。日報と週報メールの出力言語にも使われます。','인터페이스 언어이며 일일/주간 이메일 출력 언어로도 사용됩니다.'],
  ['邮件摘要模型','Email summary model','メール要約モデル','이메일 요약 모델'],
  ['邮件备用模型','Email fallback model','メール予備モデル','이메일 예비 모델'],
  ['日报模型','Daily email model','日報モデル','일일 이메일 모델'],
  ['周报模型','Weekly email model','週報モデル','주간 이메일 모델'],
  ['邮件 Ollama 超时','Email Ollama timeout','メール Ollama タイムアウト','이메일 Ollama 시간 제한'],
  ['摘要邮件发送时间、SMTP、Keychain 和日报/周报模型配置。','Summary email schedule, SMTP, Keychain, and daily/weekly model settings.','要約メールの送信時刻、SMTP、Keychain、日報/週報モデル設定。','요약 이메일 시간, SMTP, Keychain, 일일/주간 모델 설정입니다.'],
  ['保存设置','Save settings','設定を保存','설정 저장'],
  ['重载 Agent','Reload Agent','Agentを再読み込み','Agent 다시 로드'],
  ['重载同步服务','Reload sync service','同期サービスを再読み込み','동기화 서비스 다시 로드'],
  ['重载 Dashboard','Reload Dashboard','Dashboardを再読み込み','Dashboard 다시 로드'],
  ['只读','Read-only','読み取り専用','읽기 전용'],
  ['受控写入','Controlled writes','制御された書き込み','제어된 쓰기'],
  ['时区','Timezone','タイムゾーン','시간대'],
  ['采集器','Collectors','コレクタ','수집기'],
  ['移动同步','Mobile sync','モバイル同期','모바일 동기화'],
  ['文件分析','File analysis','ファイル分析','파일 분석'],
  ['分析后删除','Delete after analysis','分析後に削除','분석 후 삭제'],
  ['音频连续队列','Continuous audio queue','音声連続キュー','오디오 연속 대기열'],
  ['长期保留','Long-term retention','長期保持','장기 보존'],
  ['邮件报告','Email reports','メールレポート','이메일 보고서'],
  ['浏览器资料','Browser profiles','ブラウザプロファイル','브라우저 프로필'],
  ['限制','Limits','制限','제한'],
  ['后台 Agent','Background Agent','バックグラウンドAgent','백그라운드 Agent'],
  ['AI 路由','AI routing','AIルーティング','AI 라우팅'],
  ['本地 AI','Local AI','ローカルAI','로컬 AI'],
  ['OpenAI 备用','OpenAI fallback','OpenAI予備','OpenAI 대체'],
  ['音频分析','Audio analysis','音声分析','오디오 분석'],
  ['音频预处理','Audio preprocessing','音声前処理','오디오 전처리'],
  ['回收箱目录','Recycle bin directory','ごみ箱ディレクトリ','휴지통 디렉터리'],
  ['配置文件','Config file','設定ファイル','설정 파일'],
  ['数据目录','Data directory','データディレクトリ','데이터 디렉터리'],
  ['分析副本目录','Analysis copy directory','分析コピー先','분석 사본 디렉터리'],
  ['脱敏状态','Redaction status','マスキング状態','마스킹 상태'],
  ['项可直接调整；敏感字段已隐藏',' directly editable; sensitive fields hidden','項目を直接調整できます。機密フィールドは非表示です','개 항목 직접 조정 가능; 민감 필드는 숨김'],
  ['当前开启数量','currently enabled','現在有効な数','현재 활성화 수'],
  ['保留预览','Retention preview','保持プレビュー','보존 미리보기'],
  ['执行保留','Apply retention','保持を実行','보존 실행'],
  ['按配置启用','Enabled by config','設定により有効','설정에 따라 활성화'],
  ['保留','Retain','保持','보존'],
  ['同步上传上限','Sync upload limit','同期アップロード上限','동기화 업로드 제한'],
  ['同步清理','Sync cleanup','同期クリーンアップ','동기화 정리'],
  ['索引状态','Index status','索引状態','인덱스 상태'],
  ['重建语义索引','Rebuild semantic index','セマンティック索引を再構築','시맨틱 인덱스 재생성'],
  ['问答','Ask','質問','질문'],
  ['问本地资料','Ask local knowledge','ローカル資料に質問','로컬 자료 질문'],
  ['只搜索','Search only','検索のみ','검색만'],
  ['问答工作区','Q&A workspace','Q&Aワークスペース','Q&A 작업 공간'],
  ['本地检索、语义召回和证据问答','Local search, semantic recall, and evidence Q&A','ローカル検索、セマンティック想起、証拠Q&A','로컬 검색, 시맨틱 검색, 증거 Q&A'],
  ['语义索引','Semantic index','セマンティック索引','시맨틱 인덱스'],
  ['检索概览','Retrieval overview','検索概要','검색 개요'],
  ['语义结果','Semantic results','セマンティック結果','시맨틱 결과'],
  ['关键词记录','Keyword records','キーワード記録','키워드 기록'],
  ['答案','Answer','回答','답변'],
  ['检索','Retrieval','検索','검색'],
  ['引用','Citations','引用','인용'],
  ['证据分组','Evidence groups','証拠グループ','증거 그룹'],
  ['录音','Recordings','録音','녹음'],
  ['位置','Location','位置','위치'],
  ['语义','Semantic','セマンティック','시맨틱'],
  ['反馈','Feedback','フィードバック','피드백'],
  ['来源状态','Source status','ソース状態','소스 상태'],
  ['压缩摘要','Compact summaries','要約を圧縮','요약 압축'],
  ['全部事件','All events','すべてのイベント','모든 이벤트'],
  ['当前筛选','Current filters','現在のフィルタ','현재 필터'],
  ['筛选','Filters','フィルタ','필터'],
  ['清理到期','Clean due items','期限切れを整理','만료 항목 정리'],
  ['预览清理','Preview cleanup','クリーンアップをプレビュー','정리 미리보기'],
  ['执行清理','Apply cleanup','クリーンアップを実行','정리 실행'],
  ['搜索行动、来源、证据','Search actions, sources, or evidence','アクション、ソース、証拠を検索','작업, 소스, 증거 검색'],
  ['处理备注','Processing note','処理メモ','처리 메모'],
  ['搜索建议、来源、证据','Search suggestions, sources, or evidence','提案、ソース、証拠を検索','제안, 소스, 증거 검색'],
  ['搜索项目、关键词、行动项','Search projects, keywords, or action items','プロジェクト、キーワード、アクション項目を検索','프로젝트, 키워드, 작업 항목 검색'],
  ['项目名','Project name','プロジェクト名','프로젝트 이름'],
  ['这个项目的长期背景、目标、当前状态','Long-term background, goals, and current status for this project','このプロジェクトの長期背景、目標、現在状態','이 프로젝트의 장기 배경, 목표, 현재 상태'],
  ['关键词，用逗号分隔','Keywords, separated by commas','キーワード、カンマ区切り','키워드, 쉼표로 구분'],
  ['会议标题','Meeting title','ミーティングタイトル','회의 제목'],
  ['参与者，用逗号分隔','Participants, separated by commas','参加者、カンマ区切り','참석자, 쉼표로 구분'],
  ['议程 / 想确认的问题','Agenda / questions to confirm','議題 / 確認したい質問','안건 / 확인할 질문'],
  ['记录结论、分歧、行动项。包含“需要/确认/回复/截止”等词会进入处理队列。','Record conclusions, disagreements, and action items. Words like need, confirm, reply, or deadline will enter the inbox.','結論、相違点、アクション項目を記録します。「必要/確認/返信/締切」などの語は処理キューに入ります。','결론, 이견, 작업 항목을 기록합니다. 필요/확인/답장/마감 같은 단어는 처리 대기열에 들어갑니다.'],
  ['搜索项目、关键词、证据','Search projects, keywords, or evidence','プロジェクト、キーワード、証拠を検索','프로젝트, 키워드, 증거 검색'],
  ['项目备注','Project note','プロジェクトメモ','프로젝트 메모'],
  ['开始 HH:MM','Start HH:MM','開始 HH:MM','시작 HH:MM'],
  ['结束 HH:MM','End HH:MM','終了 HH:MM','종료 HH:MM'],
  ['搜索时间、人物、应用、地点、摘要','Search time, people, apps, places, or summaries','時間、人物、アプリ、場所、要約を検索','시간, 사람, 앱, 장소, 요약 검색'],
  ['写下哪些总结重要、不重要或需要修正','Write which summaries matter, do not matter, or need correction','重要な要約、不要な要約、修正が必要な要約を書いてください','중요한 요약, 중요하지 않은 요약, 수정이 필요한 요약 작성'],
  ['关键词或问题','Keyword or question','キーワードまたは質問','키워드 또는 질문'],
  ['向本地资料提问，例如：今天录音里有什么值得跟进？','Ask local knowledge, for example: what is worth following up from today\'s recordings?','ローカル資料に質問します。例: 今日の録音でフォローすべきことは？','로컬 자료에 질문하세요. 예: 오늘 녹음에서 후속 조치할 것은?'],
  ['筛选标题、正文、source/kind','Filter title, body, or source/kind','タイトル、本文、source/kindで絞り込み','제목, 본문, source/kind 필터'],
  ['搜索文件名、分类、路径','Search file name, category, or path','ファイル名、分類、パスを検索','파일명, 분류, 경로 검색'],
  ['搜索 ID、名字、状态、来源、一致性','Search ID, name, status, source, or consistency','ID、名前、状態、ソース、一致性を検索','ID, 이름, 상태, 소스, 일관성 검색'],
  ['搜样本：说话人、obs、转写、状态','Search samples: speaker, obs, transcript, or status','サンプル検索: 話者、obs、文字起こし、状態','샘플 검색: 화자, obs, 전사, 상태'],
  ['显示名','Display name','表示名','표시 이름'],
  ['搜索文件名、路径、正文、source/kind','Search file name, path, body, or source/kind','ファイル名、パス、本文、source/kindを検索','파일명, 경로, 본문, source/kind 검색'],
  ['搜索文件名、原路径、回收路径、分类','Search file name, original path, recycle path, or category','ファイル名、元パス、ごみ箱パス、分類を検索','파일명, 원래 경로, 휴지통 경로, 분류 검색'],
  ['回收文件路径','Recycled file path','ごみ箱内ファイルパス','휴지통 파일 경로'],
  ['恢复到指定路径，可留空','Restore to a specific path, optional','指定パスへ復元、空欄可','지정 경로로 복원, 비워둘 수 있음'],
  ['搜索时间、设备、正文、source key','Search time, device, body, or source key','時間、端末、本文、source keyを検索','시간, 기기, 본문, source key 검색'],
  ['筛选分组、字段或值','Filter groups, fields, or values','グループ、フィールド、値で絞り込み','그룹, 필드, 값 필터'],
  ['搜索本地 observations、报告和语义索引。','Search local observations, reports, and the semantic index.','ローカルobservations、レポート、セマンティック索引を検索します。','로컬 observations, 보고서, 시맨틱 인덱스를 검색합니다.'],
  ['用本地检索结果向本地模型提问。','Ask the local model using local retrieval results.','ローカル検索結果を使ってローカルモデルに質問します。','로컬 검색 결과로 로컬 모델에 질문합니다.'],
  ['刷新语义索引状态。','Refresh semantic index status.','セマンティック索引の状態を更新します。','시맨틱 인덱스 상태를 새로고침합니다.'],
  ['重建本地 embedding 索引。','Rebuild the local embedding index.','ローカルembedding索引を再構築します。','로컬 embedding 인덱스를 재생성합니다.'],
  ['按这个状态筛选音频队列。','Filter the audio queue by this status.','この状態で音声キューを絞り込みます。','이 상태로 오디오 대기열을 필터합니다.'],
  ['行动总览会合并今日重点、处理队列、修复项、项目聚类和说话人质量。','Action overview combines today highlights, inbox, repairs, project clusters, and speaker quality.','アクション概要は今日のハイライト、処理キュー、修復項目、プロジェクトクラスタ、話者品質を統合します。','작업 개요는 오늘의 핵심, 처리 대기열, 수정 항목, 프로젝트 클러스터, 화자 품질을 합칩니다.'],
  ['把录音、快速标注、修复项、项目和说话人待处理集中成一个可清空的处理队列。','Collect recordings, quick tags, repairs, projects, and speaker work into one clearable inbox.','録音、クイックタグ、修復項目、プロジェクト、話者タスクを空にできる処理キューへ集約します。','녹음, 빠른 태그, 수정 항목, 프로젝트, 화자 작업을 비울 수 있는 처리 대기열에 모읍니다.'],
  ['按证据自动聚合今天的主题、项目和相关下一步，是行动工作区里的完整项目视图。','Automatically groups today\'s topics, projects, and next steps from evidence.','証拠から今日のトピック、プロジェクト、次のステップを自動集約します。','증거를 기준으로 오늘의 주제, 프로젝트, 다음 단계를 자동으로 묶습니다.'],
  ['把每天的项目聚类和会议结论沉淀为长期项目档案。','Turn daily project clusters and meeting conclusions into long-term project files.','毎日のプロジェクトクラスタと会議結論を長期プロジェクト档案に残します。','매일의 프로젝트 클러스터와 회의 결론을 장기 프로젝트 파일로 남깁니다.'],
  ['开会时记录议程、笔记和行动项，并回写项目记忆与本地时间线。','Record agenda, notes, and action items during meetings, then write them back to memory and timeline.','会議中の議題、メモ、アクション項目を記録し、記憶とタイムラインへ書き戻します。','회의 중 안건, 메모, 작업 항목을 기록하고 기억과 타임라인에 다시 씁니다.'],
  ['打开实时日内时间线，合并应用、录音、文件、位置和提醒。','Open the live day timeline combining apps, recordings, files, locations, and reminders.','アプリ、録音、ファイル、位置、リマインダーを統合したリアルタイムの日内タイムラインを開きます。','앱, 녹음, 파일, 위치, 미리 알림을 합친 실시간 일일 타임라인을 엽니다.'],
  ['查看系统数据量、健康状态、最近采集和维护入口。','View data volume, health, recent collection, and maintenance entry points.','データ量、ヘルス状態、最近の収集、メンテナンス入口を表示します。','데이터 용량, 상태, 최근 수집, 유지관리 진입점을 봅니다.'],
  ['运行本机诊断，检查采集器、同步服务、本地 AI 和数据质量。','Run local diagnostics for collectors, sync service, local AI, and data quality.','コレクタ、同期サービス、ローカルAI、データ品質のローカル診断を実行します。','수집기, 동기화 서비스, 로컬 AI, 데이터 품질 진단을 실행합니다.'],
  ['查看移动端录音分析队列，并手动触发转写和摘要。','View the mobile recording analysis queue and manually trigger transcription and summaries.','モバイル録音分析キューを表示し、文字起こしと要約を手動実行します。','모바일 녹음 분석 대기열을 보고 전사와 요약을 수동 실행합니다.'],
  ['把样本、embedding、一致性、代表样本、自动整理和人工确认串成一个训练闭环。','Connect samples, embeddings, consistency, representative samples, auto cleanup, and manual confirmation into one training loop.','サンプル、embedding、一致性、代表サンプル、自動整理、手動確認を一つのトレーニングループにします。','샘플, embedding, 일관성, 대표 샘플, 자동 정리, 수동 확인을 하나의 훈련 루프로 연결합니다.'],
  ['对本地资料做关键词搜索、语义检索和证据问答。','Run keyword search, semantic retrieval, and evidence Q&A over local knowledge.','ローカル資料に対してキーワード検索、セマンティック検索、証拠Q&Aを行います。','로컬 자료에서 키워드 검색, 시맨틱 검색, 증거 Q&A를 실행합니다.'],
  ['查看原始事件流，适合排查某一天的底层记录。','View the raw event stream for debugging the records behind a day.','ある日の底層記録を調査するための生イベントストリームを表示します。','하루의 하위 기록을 확인하기 위한 원본 이벤트 흐름을 봅니다.'],
  ['打开日报、长期摘要、邮件摘要和反馈记录。','Open daily reports, long-term summaries, email summaries, and feedback records.','日報、長期要約、メール要約、フィードバック記録を開きます。','일일 보고서, 장기 요약, 이메일 요약, 피드백 기록을 엽니다.'],
  ['检查各数据来源是否开启、最近是否采集，以及缺少哪些前置文件。','Check whether each source is enabled, recently collected, and missing prerequisites.','各データソースが有効か、最近収集されたか、不足する前提ファイルを確認します。','각 데이터 소스의 활성화, 최근 수집, 누락된 사전 파일을 확인합니다.'],
  ['查看说话人聚类、样本、重命名和合并入口。','View speaker clusters, samples, rename, and merge actions.','話者クラスタ、サンプル、名前変更、統合入口を表示します。','화자 클러스터, 샘플, 이름 변경, 병합 작업을 봅니다.'],
  ['查看文件监控路径、分析状态，并手动扫描新文件。','View file watch paths and analysis status, and manually scan new files.','ファイル監視パスと分析状態を表示し、新規ファイルを手動スキャンします。','파일 감시 경로와 분석 상태를 보고 새 파일을 수동 스캔합니다.'],
  ['查看分析后暂存的回收文件，预览清理或恢复文件。','View recycled files staged after analysis, preview cleanup, or restore files.','分析後に一時保存されたごみ箱ファイルを表示し、整理をプレビューまたは復元します。','분석 후 임시 보관된 휴지통 파일을 보고 정리 미리보기 또는 복원합니다.'],
  ['已整合到手机同步页。','Integrated into Mobile Sync.','モバイル同期ページへ統合済みです。','모바일 동기화 페이지에 통합되었습니다.'],
  ['按当前机器状态完成首次配置、手机同步 token、Mac 服务和 iPhone 连接地址。','Complete first setup, mobile sync token, Mac services, and iPhone connection address based on this machine.','現在のMac状態に基づき初期設定、同期token、Macサービス、iPhone接続先を完了します。','현재 기기 상태에 맞춰 초기 설정, 모바일 동기화 token, Mac 서비스, iPhone 연결 주소를 완료합니다.'],
  ['集中查看敏感来源、保留策略、缓存清理、发布边界和隐私风险。','Review sensitive sources, retention policy, cache cleanup, publication boundaries, and privacy risks.','機密ソース、保持ポリシー、キャッシュ整理、公開境界、プライバシーリスクをまとめて確認します。','민감 소스, 보존 정책, 캐시 정리, 공개 범위, 개인정보 위험을 함께 봅니다.'],
  ['查看 Mac/手机连接、上传缓存、导入缓存、音频分析、去重和清理预览。','View Mac/mobile connection, upload cache, import cache, audio analysis, dedupe, and cleanup previews.','Mac/モバイル接続、アップロードキャッシュ、インポートキャッシュ、音声分析、重複排除、整理プレビューを表示します。','Mac/휴대폰 연결, 업로드 캐시, 가져오기 캐시, 오디오 분석, 중복 제거, 정리 미리보기를 봅니다.'],
  ['统一预览和执行数据库记录、运行日志、缓存和回收箱清理。','Preview and apply cleanup for database records, run logs, cache, and recycle bin in one place.','DB記録、実行ログ、キャッシュ、ごみ箱整理を一箇所でプレビューして実行します。','DB 기록, 실행 로그, 캐시, 휴지통 정리를 한 곳에서 미리보고 실행합니다.'],
  ['查看和编辑当前配置，敏感字段会被隐藏。','View and edit current settings. Sensitive fields are hidden.','現在の設定を表示・編集します。機密フィールドは非表示です。','현재 설정을 보고 편집합니다. 민감한 필드는 숨겨집니다.'],
  ['立即采集当天数据，并按配置刷新报告。','Collect today\'s data now and refresh reports according to settings.','今日のデータを今すぐ収集し、設定に従ってレポートを更新します。','오늘 데이터를 즉시 수집하고 설정에 따라 보고서를 새로고침합니다.'],
  ['处理待分析录音，生成转写、摘要和说话人线索。','Process recordings waiting for analysis and generate transcripts, summaries, and speaker clues.','分析待ち録音を処理し、文字起こし、要約、話者手がかりを生成します。','분석 대기 녹음을 처리하고 전사, 요약, 화자 단서를 생성합니다.'],
  ['重新生成今天的日报和摘要文件。','Regenerate today\'s daily report and summary files.','今日の日報と要約ファイルを再生成します。','오늘의 일일 보고서와 요약 파일을 다시 생성합니다.'],
  ['预览或执行长期保留策略，清理已压缩的旧数据。','Preview or apply long-term retention and clean compacted old data.','長期保持ポリシーをプレビューまたは実行し、圧縮済みの古いデータを整理します。','장기 보존 정책을 미리보거나 실행하고 압축된 오래된 데이터를 정리합니다.'],
  ['检查当前是否有到期的邮件摘要。','Check whether any email summaries are due.','期限になったメール要約があるか確認します。','마감된 이메일 요약이 있는지 확인합니다.'],
  ['把当天资料压缩进长期日/周/月记忆。','Compact today\'s material into long-term daily, weekly, and monthly memory.','当日の資料を長期の日次/週次/月次記憶へ圧縮します。','오늘 자료를 장기 일/주/월 기억으로 압축합니다.'],
  ['安装或重载 Mac 后台采集 LaunchAgent。','Install or reload the Mac background collector LaunchAgent.','Macバックグラウンド収集LaunchAgentをインストールまたは再読み込みします。','Mac 백그라운드 수집 LaunchAgent를 설치하거나 다시 로드합니다.'],
  ['安装或重载手机上传接收服务。','Install or reload the mobile upload receiver service.','モバイルアップロード受信サービスをインストールまたは再読み込みします。','모바일 업로드 수신 서비스를 설치하거나 다시 로드합니다.'],
  ['安装或重载桌面 dashboard 服务。','Install or reload the desktop dashboard service.','デスクトップdashboardサービスをインストールまたは再読み込みします。','데스크톱 dashboard 서비스를 설치하거나 다시 로드합니다.'],
  ['重建本地语义搜索索引，供问答和相似检索使用。','Rebuild the local semantic search index for Q&A and similarity retrieval.','Q&Aと類似検索用にローカルセマンティック検索索引を再構築します。','Q&A와 유사 검색을 위한 로컬 시맨틱 검색 인덱스를 재생성합니다.'],
  ['把选中的说话人 ID 改成真实显示名。','Rename the selected speaker ID to a real display name.','選択した話者IDを実際の表示名に変更します。','선택한 화자 ID를 실제 표시 이름으로 변경합니다.'],
  ['把自动生成的局部 Speaker 名整理成稳定的全局 Voice ID。','Convert auto-generated local Speaker names into stable global Voice IDs.','自動生成された局所Speaker名を安定したグローバルVoice IDへ整理します。','자동 생성된 로컬 Speaker 이름을 안정적인 전역 Voice ID로 정리합니다.'],
  ['把一个说话人合并到另一个说话人。','Merge one speaker into another speaker.','一人の話者を別の話者へ統合します。','한 화자를 다른 화자에 병합합니다.'],
  ['把多个已勾选的说话人一次合并到同一个目标。','Merge multiple selected speakers into one target at once.','チェックした複数話者を一つのターゲットへまとめて統合します。','선택한 여러 화자를 하나의 대상으로 한 번에 병합합니다.'],
  ['删除一个说话人及其托管样本记录。','Delete one speaker and its managed sample records.','一人の話者と管理サンプル記録を削除します。','한 화자와 관리 샘플 기록을 삭제합니다.'],
  ['删除多个已勾选的说话人及其托管样本记录。','Delete selected speakers and their managed sample records.','チェックした複数話者と管理サンプル記録を削除します。','선택한 여러 화자와 관리 샘플 기록을 삭제합니다.'],
  ['把这条样本从当前说话人中分离出来，单独新建一个 Voice。','Detach this sample from the current speaker and create a new Voice.','このサンプルを現在の話者から分離し、新しいVoiceを作成します。','이 샘플을 현재 화자에서 분리하고 새 Voice를 만듭니다.'],
  ['重新计算说话人的 embedding 聚类一致性，并刷新每条样本相对当前聚类的一致性。','Recalculate speaker embedding cluster consistency and refresh each sample against the current cluster.','話者embeddingクラスタ一致性を再計算し、各サンプルの現在クラスタへの一致性を更新します。','화자 embedding 클러스터 일관성을 다시 계산하고 각 샘플의 현재 클러스터 일관성을 새로고침합니다.'],
  ['按当前裁剪策略重裁筛选出来的说话人样本，并重新计算变更样本的 embedding。','Re-cut filtered speaker samples with the current trimming policy and recompute embeddings for changed samples.','現在の裁剪ポリシーで絞り込んだ話者サンプルを再裁剪し、変更サンプルのembeddingを再計算します。','현재 자르기 정책으로 필터된 화자 샘플을 다시 자르고 변경된 샘플의 embedding을 재계산합니다.'],
  ['按当前配置阈值自动合并相似声音，并隐藏低相似未命名 Voice。','Automatically merge similar voices at the configured threshold and hide low-similarity unnamed Voices.','現在の設定しきい値で似た声を自動統合し、低類似の未命名Voiceを非表示にします。','현재 설정 임계값으로 유사 음성을 자동 병합하고 낮은 유사도의 미명명 Voice를 숨깁니다.'],
  ['确认这些说话人整理结果正确，后续自动整理不会主动隐藏它们。','Confirm these speaker cleanup results so later auto cleanup will not hide them.','これらの話者整理結果を確認し、後続の自動整理で非表示にされないようにします。','이 화자 정리 결과를 확인하여 이후 자동 정리가 숨기지 않도록 합니다.'],
  ['把低相似隐藏 Voice 放回人工复查列表。','Return hidden low-similarity Voices to the manual review list.','低類似で非表示になったVoiceを手動レビュー一覧へ戻します。','낮은 유사도로 숨겨진 Voice를 수동 검토 목록으로 되돌립니다.'],
  ['扫描监控路径里的新文件，并用本地分析流程处理。','Scan watch paths for new files and process them with the local analysis flow.','監視パス内の新規ファイルをスキャンし、ローカル分析フローで処理します。','감시 경로의 새 파일을 스캔하고 로컬 분석 흐름으로 처리합니다.'],
  ['预览或执行回收箱到期清理。','Preview or apply cleanup for expired recycle-bin files.','ごみ箱の期限切れ整理をプレビューまたは実行します。','휴지통 만료 정리를 미리보거나 실행합니다.'],
  ['把回收箱中的文件恢复到原路径或指定路径。','Restore a recycled file to its original path or a chosen path.','ごみ箱内のファイルを元パスまたは指定パスへ復元します。','휴지통 파일을 원래 경로 또는 지정 경로로 복원합니다.'],
  ['预览或执行移动端上传缓存和无引用导入目录清理。','Preview or apply cleanup for mobile upload cache and unreferenced import directories.','モバイルアップロードキャッシュと参照なしインポートディレクトリの整理をプレビューまたは実行します。','모바일 업로드 캐시와 참조 없는 가져오기 디렉터리 정리를 미리보거나 실행합니다.'],
  ['立即更新今天的资料，不等待后台定时采集。','Update today\'s material immediately without waiting for scheduled collection.','バックグラウンド定期収集を待たずに今日の資料を即時更新します。','백그라운드 예약 수집을 기다리지 않고 오늘 자료를 즉시 업데이트합니다.'],
  ['处理今天尚未完成的录音分析。','Process today\'s unfinished recording analysis.','今日まだ完了していない録音分析を処理します。','오늘 완료되지 않은 녹음 분석을 처리합니다.'],
  ['重新读取当前页面的数据。','Reload data for the current page.','現在ページのデータを再読み込みします。','현재 페이지 데이터를 다시 읽습니다.'],
  ['按日期、时间段和关键词筛选今天的事件。','Filter today\'s events by date, time range, and keywords.','日付、時間帯、キーワードで今日のイベントを絞り込みます。','날짜, 시간대, 키워드로 오늘 이벤트를 필터합니다.'],
  ['把这条反馈保存到数据库、反馈摘要和本地检索资料里。','Save this feedback to the database, feedback summary, and local search knowledge.','このフィードバックをDB、フィードバック要約、ローカル検索資料に保存します。','이 피드백을 DB, 피드백 요약, 로컬 검색 자료에 저장합니다.'],
  ['采集今天的数据并刷新今天报告。','Collect today\'s data and refresh today\'s report.','今日のデータを収集して今日のレポートを更新します。','오늘 데이터를 수집하고 오늘 보고서를 새로고침합니다.'],
  ['基于已有数据重新生成今天报告。','Regenerate today\'s report from existing data.','既存データから今日のレポートを再生成します。','기존 데이터로 오늘 보고서를 다시 생성합니다.'],
  ['生成新的手机同步密钥并写入 config.json；旧 iPhone 配置需要同步更新。','Generate a new mobile sync key and write it to config.json; old iPhone settings must be updated.','新しいモバイル同期キーを生成してconfig.jsonへ書き込みます。古いiPhone設定も更新が必要です。','새 모바일 동기화 키를 생성해 config.json에 쓰며 기존 iPhone 설정도 업데이트해야 합니다.'],
  ['依次安装并加载同步、后台采集和 dashboard 服务。','Install and load sync, background collector, and dashboard services in sequence.','同期、バックグラウンド収集、dashboardサービスを順にインストールして読み込みます。','동기화, 백그라운드 수집, dashboard 서비스를 차례로 설치하고 로드합니다.'],
  ['复制这一项到剪贴板。','Copy this item to the clipboard.','この項目をクリップボードへコピーします。','이 항목을 클립보드에 복사합니다.'],
  ['复制刚生成的新 token。','Copy the newly generated token.','生成したばかりの新しいtokenをコピーします。','방금 생성한 새 token을 복사합니다.'],
  ['复制这个 Mac 同步地址。','Copy this Mac sync address.','このMac同期アドレスをコピーします。','이 Mac 동기화 주소를 복사합니다.'],
  ['重新运行本机诊断。','Run local diagnostics again.','ローカル診断を再実行します。','로컬 진단을 다시 실행합니다.'],
  ['从音频队列中处理最多 5 条。','Process up to 5 items from the audio queue.','音声キューから最大5件を処理します。','오디오 대기열에서 최대 5개를 처리합니다.'],
  ['从音频队列中处理最多 10 条。','Process up to 10 items from the audio queue.','音声キューから最大10件を処理します。','오디오 대기열에서 최대 10개를 처리합니다.'],
  ['从音频队列中处理最多 20 条。','Process up to 20 items from the audio queue.','音声キューから最大20件を処理します。','오디오 대기열에서 최대 20개를 처리합니다.'],
  ['从音频队列中处理最多 50 条。','Process up to 50 items from the audio queue.','音声キューから最大50件を処理します。','오디오 대기열에서 최대 50개를 처리합니다.'],
  ['清除当前筛选，显示全部记录。','Clear current filters and show all records.','現在のフィルタをクリアして全記録を表示します。','현재 필터를 지우고 모든 기록을 표시합니다.'],
  ['载入指定日期的数据。','Load data for the specified date.','指定日のデータを読み込みます。','지정한 날짜의 데이터를 불러옵니다.'],
  ['将指定说话人 ID 重命名。','Rename the specified speaker ID.','指定した話者IDを名前変更します。','지정한 화자 ID의 이름을 변경합니다.'],
  ['清空当前勾选的说话人。','Clear the currently selected speakers.','現在チェックされている話者をクリアします。','현재 선택된 화자를 지웁니다.'],
  ['勾选当前筛选结果里显示的所有说话人。','Select all speakers shown in the current filtered results.','現在の絞り込み結果に表示されている全話者をチェックします。','현재 필터 결과에 표시된 모든 화자를 선택합니다.'],
  ['切换当前筛选结果里的勾选状态。','Invert selected speakers in the current filtered results.','現在の絞り込み結果のチェック状態を反転します。','현재 필터 결과의 선택 상태를 반전합니다.'],
  ['把所有已勾选说话人合并到指定目标。','Merge all selected speakers into the specified target.','チェック済み話者をすべて指定ターゲットへ統合します。','선택된 모든 화자를 지정 대상으로 병합합니다.'],
  ['删除所有已勾选说话人、aliases、样本记录和托管样本文件。','Delete all selected speakers, aliases, sample records, and managed sample files.','チェック済み話者、aliases、サンプル記録、管理サンプルファイルをすべて削除します。','선택된 모든 화자, aliases, 샘플 기록, 관리 샘플 파일을 삭제합니다.'],
  ['永久删除已到期的回收文件。','Permanently delete expired recycled files.','期限切れのごみ箱ファイルを完全削除します。','만료된 휴지통 파일을 영구 삭제합니다.'],
  ['统一清理旧事件、运行记录、日志、缓存和回收箱。','Clean old events, run records, logs, cache, and recycle bin together.','古いイベント、実行記録、ログ、キャッシュ、ごみ箱をまとめて整理します。','오래된 이벤트, 실행 기록, 로그, 캐시, 휴지통을 함께 정리합니다.'],
  ['跳转到诊断页，检查配置关联的采集器、服务和模型。','Open Doctor to check collectors, services, and models tied to settings.','診断ページへ移動し、設定に関連するコレクタ、サービス、モデルを確認します。','진단 페이지를 열어 설정과 연결된 수집기, 서비스, 모델을 확인합니다.'],
  ['只预览长期保留策略会清理的内容。','Only preview what long-term retention would clean.','長期保持ポリシーが整理する内容だけをプレビューします。','장기 보존 정책이 정리할 내용을 미리보기만 합니다.'],
  ['执行长期保留清理策略。','Apply the long-term retention cleanup policy.','長期保持クリーンアップポリシーを実行します。','장기 보존 정리 정책을 실행합니다.'],
  ['把当前分组的可编辑配置写入 config.json。','Write editable settings in the current group to config.json.','現在グループの編集可能設定をconfig.jsonへ書き込みます。','현재 그룹의 편집 가능한 설정을 config.json에 씁니다.'],
  ['重新加载后台采集服务，让采集、音频、文件分析等配置生效。','Reload the background collector so collection, audio, and file-analysis settings take effect.','バックグラウンド収集サービスを再読み込みし、収集、音声、ファイル分析設定を反映します。','백그라운드 수집 서비스를 다시 로드해 수집, 오디오, 파일 분석 설정을 적용합니다.'],
  ['重新加载手机上传接收服务，让端口、上传限制和导入策略生效。','Reload the mobile upload receiver so port, upload limit, and import policy changes take effect.','モバイルアップロード受信サービスを再読み込みし、ポート、アップロード制限、インポート方針を反映します。','모바일 업로드 수신 서비스를 다시 로드해 포트, 업로드 제한, 가져오기 정책을 적용합니다.'],
  ['重新加载桌面 dashboard 服务。','Reload the desktop dashboard service.','デスクトップdashboardサービスを再読み込みします。','데스크톱 dashboard 서비스를 다시 로드합니다.'],
  ['没有可执行的修复项','No runnable repair items','実行可能な修復項目はありません','실행 가능한 수정 항목 없음'],
  ['当前处理队列为空','The current inbox is empty','現在の処理キューは空です','현재 처리 대기열이 비어 있음'],
  ['已创建项目记忆','Project memory created','プロジェクト記憶を作成しました','프로젝트 기억 생성됨'],
  ['创建失败','Create failed','作成に失敗しました','생성 실패'],
  ['已写入项目记忆','Saved to project memory','プロジェクト記憶へ書き込みました','프로젝트 기억에 저장됨'],
  ['写入失败','Save failed','書き込みに失敗しました','저장 실패'],
  ['项目记忆已更新','Project memory updated','プロジェクト記憶を更新しました','프로젝트 기억 업데이트됨'],
  ['更新失败','Update failed','更新に失敗しました','업데이트 실패'],
  ['会议记录已开始','Meeting notes started','会議メモを開始しました','회의 기록 시작됨'],
  ['开始失败','Start failed','開始に失敗しました','시작 실패'],
  ['会议笔记为空','Meeting note is empty','会議メモが空です','회의 메모가 비어 있음'],
  ['已记录会议笔记','Meeting note recorded','会議メモを記録しました','회의 메모 기록됨'],
  ['记录失败','Record failed','記録に失敗しました','기록 실패'],
  ['会议已结束并写入本地记忆','Meeting ended and saved to local memory','会議を終了しローカル記憶へ保存しました','회의 종료 후 로컬 기억에 저장됨'],
  ['结束失败','End failed','終了に失敗しました','종료 실패'],
  ['已更新处理状态','Processing status updated','処理状態を更新しました','처리 상태 업데이트됨'],
  ['状态更新失败','Status update failed','状態更新に失敗しました','상태 업데이트 실패'],
  ['当前列表为空','The current list is empty','現在のリストは空です','현재 목록이 비어 있음'],
  ['已更新','Updated','更新しました','업데이트됨'],
  ['已生成并保存新 token','Generated and saved a new token','新しいtokenを生成して保存しました','새 token 생성 및 저장됨'],
  ['token 生成失败','Token generation failed','token生成に失敗しました','token 생성 실패'],
  ['已复制','Copied','コピーしました','복사됨'],
  ['反馈内容为空','Feedback is empty','フィードバックが空です','피드백이 비어 있음'],
  ['已写入每日反馈','Daily feedback saved','日次フィードバックを書き込みました','일일 피드백 저장됨'],
  ['请选择说话人并输入显示名','Select a speaker and enter a display name','話者を選択し表示名を入力してください','화자를 선택하고 표시 이름을 입력하세요'],
  ['请先勾选要确认的说话人','Select speakers to confirm first','確認する話者を先に選択してください','확인할 화자를 먼저 선택하세요'],
  ['请先勾选要取消隐藏的说话人','Select speakers to unhide first','再表示する話者を先に選択してください','숨김 해제할 화자를 먼저 선택하세요'],
  ['当前队列没有可处理的说话人','No processable speakers in the current queue','現在のキューに処理可能な話者はありません','현재 대기열에 처리 가능한 화자가 없음'],
  ['当前样本筛选没有关联说话人','The current sample filter has no linked speakers','現在のサンプル絞り込みには関連話者がありません','현재 샘플 필터에 연결된 화자가 없음'],
  ['当前样本筛选没有可处理的样本','The current sample filter has no processable samples','現在のサンプル絞り込みには処理可能なサンプルがありません','현재 샘플 필터에 처리 가능한 샘플이 없음'],
  ['至少勾选两个说话人，或选择一个合并目标','Select at least two speakers, or choose a merge target','少なくとも2人の話者を選択するか、統合ターゲットを選んでください','최소 두 명의 화자를 선택하거나 병합 대상을 선택하세요'],
  ['未选择说话人，将重算全部说话人一致性','No speakers selected; recalculating consistency for all speakers','話者未選択のため、全話者の一致性を再計算します','선택된 화자가 없어 모든 화자의 일관성을 재계산합니다'],
  ['请先勾选要删除的说话人','Select speakers to delete first','削除する話者を先に選択してください','삭제할 화자를 먼저 선택하세요'],
  ['已填入说话人','Speaker filled in','話者を入力しました','화자 입력됨'],
  ['已填入恢复路径','Restore path filled in','復元パスを入力しました','복원 경로 입력됨'],
  ['执行自动整理会合并相似 Voice 并隐藏低相似未命名 Voice，继续？','Auto cleanup will merge similar Voices and hide low-similarity unnamed Voices. Continue?','自動整理は似たVoiceを統合し、低類似の未命名Voiceを非表示にします。続行しますか？','자동 정리는 유사 Voice를 병합하고 낮은 유사도의 미명명 Voice를 숨깁니다. 계속할까요?'],
  ['跑一轮训练会补齐缺失 embedding、重算样本一致性并刷新代表样本；不会自动合并。继续？','One training cycle will fill missing embeddings, recalculate sample consistency, and refresh representative samples; it will not auto-merge. Continue?','1回の訓練で不足embeddingを補完し、サンプル一致性を再計算し、代表サンプルを更新します。自動統合はしません。続行しますか？','한 번의 훈련은 누락 embedding 보완, 샘플 일관성 재계산, 대표 샘플 새로고침을 수행합니다. 자동 병합은 하지 않습니다. 계속할까요?'],
  ['自动整理相似声音：按当前配置阈值自动合并相似声音，并把低相似未命名 Voice 隐藏到单独筛选里？','Auto-clean similar voices: merge similar voices at the configured threshold and move low-similarity unnamed Voices into a separate hidden filter?','類似音声の自動整理: 現在の設定しきい値で類似音声を統合し、低類似の未命名Voiceを別の非表示フィルタへ移しますか？','유사 음성 자동 정리: 현재 설정 임계값으로 병합하고 낮은 유사도의 미명명 Voice를 별도 숨김 필터로 이동할까요?'],
  ['为已有样本补齐缺失的 speaker embedding？这会调用本地 SpeechBrain 模型，可能需要一点时间。','Fill missing speaker embeddings for existing samples? This calls the local SpeechBrain model and may take some time.','既存サンプルの不足speaker embeddingを補完しますか？ローカルSpeechBrainモデルを呼び出すため少し時間がかかる場合があります。','기존 샘플의 누락 speaker embedding을 보완할까요? 로컬 SpeechBrain 모델을 호출하므로 시간이 걸릴 수 있습니다.'],
  ['把隐藏队列里已经积累足够证据的 Voice 放回人工复查？','Return hidden Voices with enough accumulated evidence to manual review?','十分な証拠が蓄積した非表示Voiceを手動レビューへ戻しますか？','충분한 증거가 쌓인 숨겨진 Voice를 수동 검토로 되돌릴까요?'],
  ['永久删除已到期的回收箱文件？','Permanently delete expired recycle-bin files?','期限切れのごみ箱ファイルを完全削除しますか？','만료된 휴지통 파일을 영구 삭제할까요?'],
  ['执行移动端缓存清理？','Apply mobile cache cleanup?','モバイルキャッシュ整理を実行しますか？','모바일 캐시 정리를 실행할까요?'],
  ['按保留策略删除旧记录、旧运行日志和旧详细报告？','Delete old records, old run logs, and old detailed reports according to retention policy?','保持ポリシーに従い古い記録、実行ログ、詳細レポートを削除しますか？','보존 정책에 따라 오래된 기록, 실행 로그, 상세 보고서를 삭제할까요?'],
  ['按当前保留策略执行删除？','Delete according to the current retention policy?','現在の保持ポリシーに従って削除しますか？','현재 보존 정책에 따라 삭제할까요?'],
  ['执行长期保留清理？','Apply long-term retention cleanup?','長期保持クリーンアップを実行しますか？','장기 보존 정리를 실행할까요?'],
  ['确认当前队列里的','Confirm speakers in the current queue:','現在キュー内の話者を確認:','현재 대기열의 화자 확인:'],
  ['个说话人？','speakers?','人の話者？','명의 화자?'],
  ['取消隐藏当前队列里的','Unhide speakers in the current queue:','現在キュー内の話者を再表示:','현재 대기열의 화자 숨김 해제:'],
  ['按当前裁剪策略重裁','Re-cut with the current trimming policy:','現在の裁剪ポリシーで再裁剪:','현재 자르기 정책으로 다시 자르기:'],
  ['个样本？只会处理能找到源音频的样本，已确认说话人不会被重新分组。','samples? Only samples with source audio will be processed; confirmed speakers will not be regrouped.','個のサンプル？元音声が見つかるサンプルのみ処理し、確認済み話者は再グループ化されません。','개 샘플? 원본 오디오를 찾을 수 있는 샘플만 처리하며 확인된 화자는 재그룹화되지 않습니다.'],
  ['把','Merge','統合','병합'],
  ['个说话人合并到','speakers into','人の話者を次へ統合:','명의 화자를 다음 대상으로 병합:'],
  ['删除','Delete','削除','삭제'],
  ['个说话人及其托管样本记录？这个操作不能撤销。','speakers and their managed sample records? This cannot be undone.','人の話者と管理サンプル記録を削除しますか？この操作は元に戻せません。','명의 화자와 관리 샘플 기록을 삭제할까요? 이 작업은 취소할 수 없습니다.'],
  ['把这个样本从','Detach this sample from','このサンプルを次から分離:','이 샘플을 다음에서 분리:'],
  ['分离出来，并单独新建一个 Voice？','and create a separate new Voice?','して、別の新しいVoiceを作成しますか？','하고 별도의 새 Voice를 만들까요?'],
  ['无事件','No events','イベントなし','이벤트 없음'],
  ['全天','All day','終日','하루 종일'],
  ['上午','Morning','午前','오전'],
  ['下午','Afternoon','午後','오후'],
  ['晚上','Evening','夜','저녁'],
  ['深夜','Late night','深夜','심야'],
  ['凌晨','Late night','未明','새벽'],
  ['工作时间','Work hours','勤務時間','근무 시간'],
  ['日内概览','Day overview','日内概要','일일 개요'],
  ['事件','Events','イベント','이벤트'],
  ['显示','shown','表示','표시'],
  ['聊天','Chat','チャット','채팅'],
  ['提醒','Reminders','リマインダー','미리 알림'],
  ['已有Summary','With summary','要約あり','요약 있음'],
  ['最近分析','Latest analysis','最新分析','최근 분석'],
  ['重要','Important','重要','중요'],
  ['不重要','Not important','重要でない','중요하지 않음'],
  ['错了','Wrong','誤り','틀림'],
  ['纠正','Correct','修正','수정'],
  ['暂无Feedback','No feedback yet','フィードバックなし','아직 피드백 없음'],
  ['日程','Calendar','カレンダー','일정'],
  ['当前','Current','現在','현재'],
  ['处理流','Processing flow','処理フロー','처리 흐름'],
  ['清空队列','Clear queue','キューを空にする','대기열 비우기'],
  ['队列列表','Queue list','キュー一覧','대기열 목록'],
  ['优先级','Priority','優先度','우선순위'],
  ['类型','Type','種類','유형'],
  ['项目 / 主题工作台','Projects / Topic workbench','プロジェクト / トピックワークベンチ','프로젝트 / 주제 작업대'],
  ['当前归档','Archive current','現在をアーカイブ','현재 항목 보관'],
  ['Sources构成','Sources breakdown','ソース内訳','소스 구성'],
  ['Current filters没有Sources构成','No source breakdown for current filters','現在のフィルタにソース内訳はありません','현재 필터에 소스 구성이 없음'],
  ['没有匹配的项目','No matching projects','一致するプロジェクトはありません','일치하는 프로젝트 없음'],
  ['长期项目档案','Long-term project files','長期プロジェクト档案','장기 프로젝트 파일'],
  ['暂停','Paused','一時停止','일시 중지'],
  ['新建项目','New project','新規プロジェクト','새 프로젝트'],
  ['还没有项目记忆；可以从今日项目聚类或会议结束时写入。','No project memory yet. You can save it from today\'s project clusters or when a meeting ends.','プロジェクト記憶はまだありません。今日のプロジェクトクラスタまたは会議終了時に保存できます。','아직 프로젝트 기억이 없습니다. 오늘의 프로젝트 클러스터나 회의 종료 시 저장할 수 있습니다.'],
  ['今日可沉淀项目','Projects to save today','今日保存できるプロジェクト','오늘 저장 가능한 프로젝트'],
  ['今天还没有明显项目聚类','No clear project clusters today','今日は明確なプロジェクトクラスタがまだありません','오늘 뚜렷한 프로젝트 클러스터가 아직 없음'],
  ['还没有活跃项目；可以先去项目记忆创建，或直接开始无项目会议。','No active projects yet. Create one in Project Memory, or start a meeting without a project.','アクティブなプロジェクトはまだありません。プロジェクト記憶で作成するか、プロジェクトなしで会議を開始できます。','아직 활성 프로젝트가 없습니다. 프로젝트 기억에서 만들거나 프로젝트 없이 회의를 시작할 수 있습니다.'],
  ['还没有会议记录','No meeting records yet','会議記録はまだありません','아직 회의 기록 없음'],
  ['Meeting流转','Meeting flow','会議フロー','회의 흐름'],
  ['不关联项目','No linked project','関連プロジェクトなし','연결된 프로젝트 없음'],
  ['扫描新文件','Scan new files','新規ファイルをスキャン','새 파일 스캔'],
  ['查看回收箱','View recycle bin','ごみ箱を表示','휴지통 보기'],
  ['文件事件','File events','ファイルイベント','파일 이벤트'],
  ['有正文','Has body','本文あり','본문 있음'],
  ['大文件','Large files','大容量ファイル','큰 파일'],
  ['扫描间隔','Scan interval','スキャン間隔','스캔 간격'],
  ['稳定等待','Stability wait','安定待ち','안정 대기'],
  ['每轮上限','Per-run limit','1回の上限','회당 제한'],
  ['工作区','Workspace','ワークスペース','작업 공간'],
  ['支持格式','Supported formats','対応形式','지원 형식'],
  ['跳过格式','Skipped formats','スキップ形式','건너뛸 형식'],
  ['跳过目录','Skipped folders','スキップフォルダ','건너뛸 폴더'],
  ['记录','Records','記録','기록'],
  ['问题','Issues','問題','문제'],
  ['最近','Recent','最近','최근'],
  ['最近记录','Recent records','最近の記録','최근 기록'],
  ['设备','Device','端末','기기'],
  ['本机','Local Mac','ローカルMac','로컬 Mac'],
  ['采集与排查','Collect & inspect','収集と調査','수집 및 점검'],
  ['按记录数','By record count','記録数順','기록 수 기준'],
  ['队列状态','Queue status','キュー状態','대기열 상태'],
  ['批处理','Batch processing','一括処理','일괄 처리'],
  ['队列明细','Queue details','キュー詳細','대기열 상세'],
  ['状态分布','Status breakdown','状態分布','상태 분포'],
  ['覆盖率','Coverage','カバレッジ','범위'],
  ['自动整理相似声音','Auto-clean similar voices','類似音声を自動整理','유사 음성 자동 정리'],
  ['重算全部一致性','Recalculate all consistency','全一致性を再計算','전체 일관성 재계산'],
  ['整理自动名','Normalize automatic names','自動名を整理','자동 이름 정리'],
  ['补 embedding','Fill embeddings','embeddingを補完','embedding 보완'],
  ['复活隐藏队列','Revive hidden queue','非表示キューを復活','숨김 대기열 복원'],
  ['整理待确认','Cleanup needs confirmation','整理確認待ち','정리 확인 필요'],
  ['低一致性','Low consistency','低一致性','낮은 일관성'],
  ['人工复查','Manual review','手動レビュー','수동 검토'],
  ['隐藏','Hidden','非表示','숨김'],
  ['优先待清洗','Priority cleanup','優先整理','우선 정리'],
  ['最近出现','Recently seen','最近出現','최근 발견'],
  ['样本最多','Most samples','サンプル最多','샘플 최다'],
  ['一致性最高','Highest consistency','一致性最高','일관성 최고'],
  ['ID 顺序','ID order','ID順','ID 순서'],
  ['当前队列','Current queue','現在のキュー','현재 대기열'],
  ['需处理','Needs work','対応が必要','처리 필요'],
  ['缺 embedding','Missing embedding','embedding不足','embedding 누락'],
  ['可播放','Playable','再生可能','재생 가능'],
  ['已分离','Detached','分離済み','분리됨'],
  ['当前队列样本','Current queue samples','現在キューのサンプル','현재 대기열 샘플'],
  ['选中说话人样本','Selected speaker samples','選択話者サンプル','선택 화자 샘플'],
  ['全部样本','All samples','すべてのサンプル','모든 샘플'],
  ['问题优先','Issues first','問題優先','문제 우선'],
  ['最新样本','Newest samples','最新サンプル','최신 샘플'],
  ['按说话人','By speaker','話者別','화자 기준'],
  ['时长最长','Longest duration','最長時間','가장 긴 길이'],
  ['待选择','No selection','選択待ち','선택 대기'],
  ['近期匹配记录','Recent match records','最近の照合記録','최근 매칭 기록'],
  ['未开始','Not started','未開始','시작 전'],
  ['待训练','Needs training','訓練待ち','훈련 필요'],
  ['样本问题','Sample issues','サンプル問題','샘플 문제'],
  ['稳定','Stable','安定','안정'],
  ['样本库','Sample library','サンプルライブラリ','샘플 라이브러리'],
  ['重算一致性','Recalculate consistency','一致性を再計算','일관성 재계산'],
  ['自动整理','Auto cleanup','自動整理','자동 정리'],
  ['自动整理后复查','Review after auto cleanup','自動整理後に再確認','자동 정리 후 검토'],
  ['人工确认','Manual confirmation','手動確認','수동 확인'],
  ['样本队列没有待处理项','Sample queue has no pending items','サンプルキューに保留項目はありません','샘플 대기열에 대기 항목 없음'],
  ['最近整理','Recent cleanup','最近の整理','최근 정리'],
  ['暂无整理记录','No cleanup records yet','整理記録はまだありません','아직 정리 기록 없음'],
  ['重载服务','Reload service','サービスを再読み込み','서비스 다시 로드'],
  ['连接与导入','Connection & import','接続とインポート','연결 및 가져오기'],
  ['在线','Online','オンライン','온라인'],
  ['上次捕获','Last capture','前回キャプチャ','마지막 캡처'],
  ['待导入','Pending import','インポート待ち','가져오기 대기'],
  ['有正文','Has body','本文あり','본문 있음'],
  ['服务与操作','Service & actions','サービスと操作','서비스 및 작업'],
  ['服务详情','Service details','サービス詳細','서비스 상세'],
  ['最近移动端记录','Recent mobile records','最近のモバイル記録','최근 모바일 기록'],
  ['上传与导入缓存','Upload & import cache','アップロードとインポートキャッシュ','업로드 및 가져오기 캐시'],
  ['删除目录','Delete folders','ディレクトリ削除','디렉터리 삭제'],
  ['可释放','Reclaimable','解放可能','회수 가능'],
  ['导入策略','Import policy','インポート方針','가져오기 정책'],
  ['本地记录','Local records','ローカル記録','로컬 기록'],
  ['高敏开启','Sensitive on','機密オン','민감 켜짐'],
  ['保留候选','Retention candidates','保持候補','보존 후보'],
  ['可清缓存','Cleanable cache','整理可能キャッシュ','정리 가능 캐시'],
  ['高敏','Sensitive','機密','민감'],
  ['保留文本','Retained text','保持テキスト','보존 텍스트'],
  ['已关闭','Off','オフ','꺼짐'],
  ['来源详情','Source details','ソース詳細','소스 상세'],
  ['查来源','Check sources','ソース確認','소스 확인'],
  ['原始事件','Raw events','生イベント','원본 이벤트'],
  ['应用样本','App samples','アプリサンプル','앱 샘플'],
  ['详细报告','Detailed reports','詳細レポート','상세 보고서'],
  ['保存保留策略','Save retention policy','保持ポリシーを保存','보존 정책 저장'],
  ['重新预览','Preview again','再プレビュー','다시 미리보기'],
  ['查看 dry-run 输出','View dry-run output','dry-run出力を表示','dry-run 출력 보기'],
  ['移动缓存文件','Mobile cached files','モバイルキャッシュファイル','모바일 캐시 파일'],
  ['移动导入目录','Mobile import folders','モバイルインポートディレクトリ','모바일 가져오기 디렉터리'],
  ['回收箱项目','Recycle bin items','ごみ箱項目','휴지통 항목'],
  ['到期回收文件','Expired recycled files','期限切れごみ箱ファイル','만료된 휴지통 파일'],
  ['记录预览','Record preview','記録プレビュー','기록 미리보기'],
  ['执行记录清理','Apply record cleanup','記録整理を実行','기록 정리 실행'],
  ['缓存预览','Cache preview','キャッシュプレビュー','캐시 미리보기'],
  ['回收箱预览','Recycle bin preview','ごみ箱プレビュー','휴지통 미리보기'],
  ['先预览，再执行','Preview before applying','実行前にプレビュー','실행 전 미리보기'],
  ['查看 retention dry-run 输出','View retention dry-run output','retention dry-run出力を表示','retention dry-run 출력 보기'],
  ['暂存概览','Staging overview','一時保存概要','임시 보관 개요'],
  ['暂存文件','Staged files','一時保存ファイル','임시 보관 파일'],
  ['占用空间','Storage used','使用容量','사용 공간'],
  ['到期可删','Due for deletion','削除期限到来','삭제 예정'],
  ['保留期','Retention window','保持期間','보존 기간'],
  ['下次','Next','次回','다음'],
  ['到期','Due','期限到来','만료'],
  ['手机音频','Mobile audio','モバイル音声','모바일 오디오'],
  ['缺失','Missing','不足','누락'],
  ['未知','Unknown','不明','알 수 없음'],
  ['空目录','Empty folders','空ディレクトリ','빈 디렉터리'],
  ['回收文件','Recycled files','ごみ箱ファイル','휴지통 파일'],
  ['路径','Path','パス','경로'],
  ['扫描清理','Scan cleanup','スキャン整理','스캔 정리'],
  ['维护清理','Maintenance cleanup','メンテナンス整理','유지관리 정리'],
  ['最近日报','Latest daily report','最新日報','최근 일일 보고서'],
  ['手机同步 token','Mobile sync token','モバイル同期token','모바일 동기화 token'],
  ['状态','Status','状態','상태'],
  ['证据','Evidence','証拠','증거'],
  ['样本','Samples','サンプル','샘플'],
  ['分析','Analysis','分析','분석'],
  ['已分析','Analyzed','分析済み','분석됨'],
  ['已有分析','Analyzed','分析済み','분석됨'],
  ['已处理','Processed','処理済み','처리됨'],
  ['上次','Last','前回','마지막'],
  ['扫描','Scan','スキャン','스캔'],
  ['通信','Messaging','通信','메시지'],
  ['同步','Sync','同期','동기화'],
  ['总数','Total','合計','총계'],
  ['小时','hours','時間','시간'],
  ['天','days','日','일'],
  ['项目动作','Project actions','プロジェクト操作','프로젝트 작업'],
  ['项目列表','Project list','プロジェクト一覧','프로젝트 목록'],
  ['当前筛选没有来源构成','No source breakdown for current filters','現在のフィルタにソース内訳はありません','현재 필터에 소스 구성이 없음'],
  ['来源构成','Source breakdown','ソース内訳','소스 구성'],
  ['没有匹配的项目聚类','No matching project clusters','一致するプロジェクトクラスタはありません','일치하는 프로젝트 클러스터 없음'],
  ['没有进行中的会议','No meeting in progress','進行中の会議はありません','진행 중인 회의 없음'],
  ['会议进行中','Meeting in progress','会議中','회의 진행 중'],
  ['会议流转','Meeting flow','会議フロー','회의 흐름'],
  ['已有摘要','With summary','要約あり','요약 있음'],
  ['暂无反馈','No feedback yet','フィードバックなし','아직 피드백 없음'],
  ['今天待处理','Pending today','今日の保留','오늘 대기'],
  ['活跃说话人','Active speakers','アクティブ話者','활성 화자'],
  ['全部说话人','All speakers','すべての話者','전체 화자'],
  ['说话人列表','Speaker list','話者一覧','화자 목록'],
  ['低一致性说话人','Low-consistency speakers','低一致性話者','낮은 일관성 화자'],
  ['隐藏低相似 Voice','Hidden low-similarity Voices','低類似で非表示のVoice','낮은 유사도로 숨겨진 Voice'],
  ['正常','Normal','正常','정상'],
  ['已确认','Confirmed','確認済み','확인됨'],
  ['已接受','Accepted','承認済み','승인됨'],
  ['已隐藏','Hidden','非表示済み','숨겨짐'],
  ['待确认','Needs confirmation','確認待ち','확인 필요'],
  ['待复查','Needs review','レビュー待ち','검토 필요'],
  ['待评分','Needs scoring','スコア待ち','점수 필요'],
  ['低一致性','Low consistency','低一致性','낮은 일관성'],
  ['自动整理待确认','Auto cleanup pending confirmation','自動整理の確認待ち','자동 정리 확인 필요'],
  ['合并后需确认','Confirm after merge','統合後に確認','병합 후 확인 필요'],
  ['隐藏低相似','Hide low-similarity','低類似を非表示','낮은 유사도 숨김'],
  ['默认不再打扰','Hidden by default','デフォルトで非表示','기본적으로 숨김'],
  ['样本无法匹配','Samples cannot match','サンプル照合不可','샘플 매칭 불가'],
  ['人物档案锚点','Profile anchors','人物档案アンカー','프로필 앵커'],
  ['已选','selected','選択済み','선택됨'],
  ['点击卡片选择','Click a card to select','カードをクリックして選択','카드를 클릭해 선택'],
  ['队列','Queue','キュー','대기열'],
  ['代表','Representative','代表','대표'],
  ['选择一个说话人或筛选队列','Select a speaker or filter queue','話者またはフィルタキューを選択','화자 또는 필터 대기열 선택'],
  ['这里会自动出现和当前上下文相关的按钮，其它按钮保持隐藏。','Contextual buttons appear here automatically; other buttons stay hidden.','現在のコンテキストに関連するボタンが自動表示され、他のボタンは非表示のままです。','현재 컨텍스트에 맞는 버튼이 자동으로 나타나며 다른 버튼은 숨겨집니다.'],
  ['点击一个说话人、队列筛选或 sample 筛选后，相关按钮会自动出现。','Click a speaker, queue filter, or sample filter to show related buttons.','話者、キューフィルタ、sampleフィルタをクリックすると関連ボタンが表示されます。','화자, 대기열 필터, sample 필터를 클릭하면 관련 버튼이 표시됩니다.'],
  ['先用队列筛说话人；点卡片后下方样本会立刻切到选中说话人。批量确认、恢复和重算在右侧一次完成。','Filter speakers with the queue first. After clicking a card, samples below switch to the selected speaker. Batch confirm, restore, and recalculation are on the right.','まずキューで話者を絞り込みます。カードをクリックすると下のサンプルが選択話者へ切り替わります。一括確認、復元、再計算は右側で行います。','먼저 대기열로 화자를 필터하세요. 카드를 클릭하면 아래 샘플이 선택한 화자로 전환됩니다. 일괄 확인, 복원, 재계산은 오른쪽에서 처리합니다.'],
  ['当前筛选没有需要训练的 speaker','No speakers need training in the current filter','現在のフィルタに訓練が必要なspeakerはありません','현재 필터에 훈련이 필요한 speaker 없음'],
  ['样本队列没有待处理项','Sample queue has no pending items','サンプルキューに保留項目はありません','샘플 대기열에 대기 항목 없음'],
  ['跑一轮训练','Run one training cycle','訓練を1回実行','훈련 1회 실행'],
  ['一致性','Consistency','一致性','일관성'],
  ['查看来源','View sources','ソースを表示','소스 보기'],
  ['查看Sources','View sources','ソースを表示','소스 보기'],
  ['执行缓存清理','Apply cache cleanup','キャッシュ整理を実行','캐시 정리 실행'],
  ['清理回收箱','Clean recycle bin','ごみ箱を整理','휴지통 정리'],
  ['清理Recycle Bin','Clean recycle bin','ごみ箱を整理','휴지통 정리'],
  ['Recycle Bin预览','Recycle bin preview','ごみ箱プレビュー','휴지통 미리보기'],
  ['Recycle Bin项目','Recycle bin items','ごみ箱項目','휴지통 항목'],
  ['回收箱条目','Recycle bin items','ごみ箱項目','휴지통 항목'],
  ['App 样本','App samples','アプリサンプル','앱 샘플'],
  ['应用样本','App samples','アプリサンプル','앱 샘플'],
  ['天保留','days retention','日保持','일 보존'],
  ['恢复','Restore','復元','복원'],
  ['路径','Path','パス','경로'],
  ['秒','sec','秒','초'],
  ['轮','run','回','회'],
  ['个',' ','件','개'],
  ['组','groups','グループ','그룹'],
  ['项','items','項目','개'],
  ['条','items','件','개'],
  ['开启数量','enabled count','有効数','활성화 수'],
  ['Mac 端数据来源开关，决定后台会采集哪些本机信号。','Mac-side source toggles decide which local signals the background collector records.','Mac側のデータソース切替で、バックグラウンド収集が記録するローカル信号を決めます。','Mac 측 데이터 소스 스위치가 백그라운드 수집기가 기록할 로컬 신호를 결정합니다.'],
  ['决定分析和问答优先走本地模型还是外部 provider。','Controls whether analysis and Q&A prefer local models or an external provider.','分析とQ&Aでローカルモデルを優先するか外部providerを使うかを決めます。','분석과 Q&A가 로컬 모델 또는 외부 provider를 우선할지 결정합니다.'],
  ['Ollama、转写后端和本地模型配置。','Ollama, transcription backend, and local model settings.','Ollama、文字起こしバックエンド、ローカルモデル設定。','Ollama, 전사 백엔드, 로컬 모델 설정입니다.'],
  ['外部 OpenAI 分析配置；敏感字段在这里不会明文显示。','External OpenAI analysis settings; sensitive fields are not shown in plain text here.','外部OpenAI分析設定。機密フィールドはここでは平文表示されません。','외부 OpenAI 분석 설정입니다. 민감한 필드는 여기에서 평문으로 표시되지 않습니다.'],
  ['移动录音转写、摘要、队列处理和音频清理策略。','Mobile recording transcription, summary, queue, and audio cleanup policy.','モバイル録音の文字起こし、要約、キュー処理、音声クリーンアップ方針。','모바일 녹음 전사, 요약, 대기열 처리, 오디오 정리 정책입니다.'],
  ['ASR/diarization 前的人声增强、speaker sample 增强和重叠说话候选分离。','Voice enhancement before ASR/diarization, speaker sample enhancement, and overlap candidate separation.','ASR/diarization前の音声強化、話者サンプル強化、重複発話候補の分離。','ASR/diarization 전 음성 강화, 화자 샘플 강화, 겹침 발화 후보 분리입니다.'],
  ['说话人聚类、样本和后续重命名合并的识别参数。','Recognition parameters for speaker clustering, samples, renaming, and merges.','話者クラスタリング、サンプル、後続の名前変更と統合の認識パラメータ。','화자 클러스터링, 샘플, 이후 이름 변경과 병합을 위한 인식 매개변수입니다.'],
  ['iPhone / Watch 上传入口、去重、导入后分析和缓存清理。','iPhone / Watch upload endpoint, dedupe, post-import analysis, and cache cleanup.','iPhone / Watchアップロード入口、重複排除、インポート後分析、キャッシュ整理。','iPhone / Watch 업로드 진입점, 중복 제거, 가져오기 후 분석, 캐시 정리입니다.'],
  ['监控文件、分析副本、include/exclude 后缀和分析后移动策略。','Watch files, analysis copies, include/exclude suffixes, and post-analysis move policy.','監視ファイル、分析コピー、include/exclude拡張子、分析後移動方針。','감시 파일, 분석 사본, include/exclude 접미사, 분석 후 이동 정책입니다.'],
  ['分析后暂存文件的保留时间、清理和恢复边界。','Retention, cleanup, and restore boundaries for files staged after analysis.','分析後に一時保存したファイルの保持時間、整理、復元境界。','분석 후 임시 보관 파일의 보존 시간, 정리, 복원 범위입니다.'],
  ['日报、周报、月报和旧记录清理窗口。','Daily, weekly, monthly report and old-record cleanup windows.','日報、週報、月報、古い記録の整理期間。','일일/주간/월간 보고서와 오래된 기록 정리 기간입니다.'],
  ['摘要邮件发送时间、SMTP 和 Keychain 配置。','Summary email schedule, SMTP, and Keychain settings.','要約メールの送信時刻、SMTP、Keychain設定。','요약 이메일 발송 시간, SMTP, Keychain 설정입니다.'],
  ['文件分析会扫描的桌面端目录。','Desktop directories scanned by file analysis.','ファイル分析がスキャンするデスクトップ側ディレクトリ。','파일 분석이 스캔하는 데스크톱 디렉터리입니다.'],
  ['浏览器历史或书签采集所需的 profile 路径。','Profile paths needed for browser history or bookmark collection.','ブラウザ履歴またはブックマーク収集に必要なprofileパス。','브라우저 기록 또는 북마크 수집에 필요한 profile 경로입니다.'],
  ['单次采集、分析或导入的安全上限。','Safety limits for a single collection, analysis, or import.','1回の収集、分析、インポートの安全上限。','단일 수집, 분석 또는 가져오기의 안전 한도입니다.'],
  ['LaunchAgent、采集频率和后台运行参数。','LaunchAgent, collection cadence, and background runtime parameters.','LaunchAgent、収集頻度、バックグラウンド実行パラメータ。','LaunchAgent, 수집 주기, 백그라운드 실행 매개변수입니다.'],
  ['采集前台 App','Collect foreground app','前面Appを収集','전면 앱 수집'],
  ['采集日历','Collect calendar','カレンダーを収集','캘린더 수집'],
  ['采集提醒事项','Collect reminders','リマインダーを収集','미리 알림 수집'],
  ['采集浏览器','Collect browsers','ブラウザを収集','브라우저 수집'],
  ['采集最近文件','Collect recent files','最近のファイルを収集','최근 파일 수집'],
  ['采集 Messages','Collect Messages','Messagesを収集','Messages 수집'],
  ['采集 Apple Mail','Collect Apple Mail','Apple Mailを収集','Apple Mail 수집'],
  ['采集照片位置','Collect photo locations','写真位置を収集','사진 위치 수집'],
  ['查看该分组原始 JSON','View raw JSON for this group','このグループの生JSONを表示','이 그룹의 원본 JSON 보기'],
  ['secret/token/key 已隐藏或显示为 configured','secret/token/key values are hidden or shown as configured','secret/token/keyは非表示、またはconfiguredとして表示されます','secret/token/key 값은 숨겨지거나 configured로 표시됩니다'],
  ['当前没有待处理行动','No pending actions','保留中のアクションはありません','대기 중인 작업 없음'],
  ['暂无手机快速标注','No mobile quick tags','モバイルクイックタグなし','모바일 빠른 태그 없음'],
  ['语义搜索索引为空','Semantic search index is empty','セマンティック検索索引が空です','시맨틱 검색 인덱스가 비어 있음'],
  ['问答无法使用语义相似证据。','Q&A cannot use semantic similarity evidence.','Q&Aでセマンティック類似証拠を使用できません。','Q&A에서 시맨틱 유사 증거를 사용할 수 없습니다.'],
  ['建立语义索引','Build semantic index','セマンティック索引を構築','시맨틱 인덱스 생성'],
  ['今天还没有形成明显项目聚类','No clear project clusters today','今日は明確なプロジェクトクラスタがまだありません','오늘 뚜렷한 프로젝트 클러스터가 아직 없음'],
  ['今天还没有可展示重点','No highlights to show today','今日は表示できるハイライトがまだありません','오늘 표시할 핵심 항목 없음'],
  ['说话人质量目前没有明显待处理项','Speaker quality has no obvious pending items','話者品質に明確な保留項目はありません','화자 품질에 뚜렷한 대기 항목이 없음'],
  ['没有匹配的配置分组','No setting groups match','一致する設定グループはありません','일치하는 설정 그룹 없음'],
  ['这个分组暂时没有开放直接编辑。敏感字段和高风险命令类配置仍保留为只读。','This group is not directly editable yet. Sensitive fields and high-risk command settings remain read-only.','このグループはまだ直接編集できません。機密項目と高リスクなコマンド設定は読み取り専用です。','이 그룹은 아직 직접 편집할 수 없습니다. 민감한 필드와 고위험 명령 설정은 읽기 전용입니다.'],
  ['保存会立即写入 config.json；后台采集或同步进程通常需要重载后才会使用新配置。','Saving writes to config.json immediately. Background collector or sync processes usually need a reload before they use the new settings.','保存するとすぐにconfig.jsonへ書き込まれます。バックグラウンドの収集や同期プロセスは通常、再読み込み後に新設定を使います。','저장하면 즉시 config.json에 기록됩니다. 백그라운드 수집 또는 동기화 프로세스는 보통 다시 로드해야 새 설정을 사용합니다.'],
  ['没有检查项','No checks','チェック項目なし','검사 항목 없음'],
  ['没有服务状态','No service status','サービス状態なし','서비스 상태 없음'],
  ['没有可用 URL；请确认同步端口配置。','No available URL. Check the sync port configuration.','利用可能なURLがありません。同期ポート設定を確認してください。','사용 가능한 URL이 없습니다. 동기화 포트 설정을 확인하세요.'],
  ['No records','No records','記録なし','기록 없음'],
  ['No reports','No reports','レポートなし','보고서 없음'],
  ['No citations','No citations','引用なし','인용 없음'],
  ['No settings selected','No settings selected','設定が選択されていません','선택된 설정 없음'],
  ['No settings','No settings','設定なし','설정 없음'],
  ['No settings in this group','No settings in this group','このグループに設定はありません','이 그룹에 설정 없음'],
  ['No health checks','No health checks','ヘルスチェックなし','상태 검사 없음'],
  ['No failures','No failures','失敗なし','실패 없음'],
  ['No mobile records','No mobile records','モバイル記録なし','모바일 기록 없음'],
  ['Run checks','Run checks','チェックを実行','검사 실행'],
  ['All','All','すべて','전체'],
  ['Search','Search','検索','검색'],
  ['Refresh','Refresh','更新','새로고침'],
  ['Load','Load','読み込み','로드'],
  ['Rename','Rename','名前変更','이름 변경'],
  ['Merge','Merge','統合','병합'],
  ['Restore','Restore','復元','복원'],
  ['Scan now','Scan now','今すぐスキャン','지금 스캔'],
  ['Purge dry-run','Purge dry-run','削除プレビュー','삭제 미리보기'],
  ['Purge due now','Purge due now','期限切れを削除','만료 항목 삭제'],
  ['Cleanup dry-run','Cleanup dry-run','クリーンアッププレビュー','정리 미리보기'],
  ['Apply cleanup','Apply cleanup','クリーンアップを適用','정리 적용'],
  ['Apply retention','Apply retention','保持を適用','보존 적용'],
  ['Index status','Index status','索引状態','인덱스 상태'],
  ['Build semantic index','Build semantic index','セマンティック索引を構築','시맨틱 인덱스 생성'],
  ['Ask local data','Ask local data','ローカルデータに質問','로컬 데이터 질문'],
  ['OK','OK','OK','확인'],
  ['FAILED','FAILED','失敗','실패'],
  ['ok','OK','OK','정상'],
  ['warn','Warning','警告','경고'],
  ['fail','Fail','失敗','실패'],
  ['error','Error','エラー','오류'],
  ['pending','Pending','保留中','대기 중'],
  ['disabled','Disabled','無効','비활성'],
  ['empty','Empty','空','비어 있음'],
  ['processing','Processing','処理中','처리 중'],
  ['skipped','Skipped','スキップ','건너뜀'],
  ['observation','Observation','観測','관측'],
  ['activity','Activity','アクティビティ','활동'],
  ['confirmed','Confirmed','確認済み','확인됨'],
  ['accepted','Accepted','承認済み','승인됨'],
  ['named','Named','命名済み','이름 지정됨'],
  ['open','Open','未処理','미처리'],
  ['done','Done','完了','완료'],
  ['archived','Archived','アーカイブ済み','보관됨'],
  ['dismissed','Dismissed','無視済み','무시됨']
];
const translationMap = {};
translationRows.forEach(([source, en, ja, ko]) => {
  const row = {zh: source, en, ja, ko};
  [source, en, ja, ko].filter(Boolean).forEach(key => {
    if(!translationMap[key]) translationMap[key] = row;
    const lowerKey = String(key).toLowerCase();
    if(!translationMap[lowerKey]) translationMap[lowerKey] = row;
  });
});
const fragmentTranslationKeys = Object.keys(translationMap)
  .filter(key => /[一-龥]/.test(key) && (key.length > 1 || ['个','组','项','条','秒','轮'].includes(key)))
  .sort((a,b) => b.length - a.length);
function currentLanguage(){ return normalizeLanguage(activeLanguage); }
function languageHtmlTag(lang=currentLanguage()){
  return ({en:'en', zh:'zh-CN', ja:'ja-JP', ko:'ko-KR'})[normalizeLanguage(lang)] || 'en';
}
function translationFor(text, lang=currentLanguage()){
  const key = String(text ?? '');
  const row = translationMap[key] || translationMap[key.toLowerCase()];
  return row ? (row[normalizeLanguage(lang)] || row.en || String(text ?? '')) : null;
}
function t(text){ return translationFor(text) || String(text ?? ''); }
function translateText(text){
  const raw = String(text ?? '');
  if(!raw.trim()) return raw;
  const leading = raw.match(/^\s*/)?.[0] || '';
  const trailing = raw.match(/\s*$/)?.[0] || '';
  const core = raw.slice(leading.length, raw.length - trailing.length);
  const direct = translationFor(core);
  if(direct) return leading + direct + trailing;
  if(currentLanguage() === 'zh' || core.length > 180) return raw;
  let output = core;
  fragmentTranslationKeys.forEach(key => {
    const translated = translationFor(key);
    if(translated && translated !== key && output.includes(key)) output = output.split(key).join(translated);
  });
  return leading + output + trailing;
}
function setDocumentLanguage(){
  document.documentElement.lang = languageHtmlTag();
}
const sectionGroups = {
  today:'日常', action:'日常', inbox:'日常', projects:'日常', memory:'日常', meeting:'日常',
  search:'记忆', personal:'记忆', files:'记忆', sources:'记忆', reports:'记忆',
  audio:'音频', 'speaker-training':'音频', speakers:'音频',
  setup:'系统', privacy:'系统', sync:'系统', doctor:'系统', settings:'系统',
  overview:'系统', timeline:'日常', recycle:'系统', maintenance:'系统'
};
const navParents = {
  timeline:'today',
  inbox:'action', suggestions:'inbox', projects:'action', memory:'action', meeting:'action',
  'speaker-training':'audio', speakers:'audio',
  personal:'search', files:'search', sources:'search', reports:'search',
  overview:'setup', recycle:'setup', privacy:'setup', sync:'setup', doctor:'setup', settings:'setup', maintenance:'setup'
};
const sectionTabs = {
  today: [['today','日内时间线'], ['timeline','原始记录']],
  action: [['action','行动总览'], ['inbox','处理队列'], ['projects','项目聚类'], ['memory','项目记忆'], ['meeting','会议']],
  search: [['search','资料问答'], ['personal','个人档案'], ['reports','报告'], ['files','文件'], ['sources','来源']],
  audio: [['audio','录音队列'], ['speakers','说话人整理'], ['speaker-training','训练闭环']],
  setup: [['setup','启动向导'], ['sync','手机同步'], ['privacy','隐私保留'], ['doctor','诊断'], ['settings','配置'], ['maintenance','维护'], ['recycle','回收箱'], ['overview','系统总览']]
};
const state = { language: activeLanguage, section: 'today', setupToken: '', actionDate: 'today', inboxDate: 'today', inboxStatus: 'active', inboxPriority: 'all', inboxSource: 'all', inboxType: 'all', inboxQ: '', suggestionDate: 'today', suggestionStatus: 'active', suggestionPriority: 'all', suggestionSource: 'all', suggestionQ: '', projectDate: 'today', projectStatus: 'active', projectSource: 'all', projectQ: '', memoryDate: 'today', memoryStatus: 'active', memoryQ: '', personalDate: 'today', personalStatus: 'confirmed', personalType: 'all', personalQ: '', meetingProjectId: '', meetingTitle: '', privacyView: 'all', reportPath: '', reportQ: '', reportCategory: 'all', audioStatus: '', speakerTrainingView: 'needs_work', sourceView: 'all', speakerView: 'active', speakerQ: '', speakerSort: 'review', speakerSelectedIds: [], speakerShownIds: [], speakerBulkTarget: '', speakerSamplesFor: 'visible', speakerSampleView: 'all', speakerSampleQ: '', speakerSampleSort: 'needs_work', speakerContextSource: 'idle', speakerSamples: [], fileView: 'all', fileQ: '', recycleView: 'all', recycleQ: '', syncView: 'all', syncQ: '', settingsGroup: 'collectors', settingsQ: '', timelineDate: 'today', timelineQ: '', timelineSource: 'all', timelineType: 'all', todayDate: 'today', todayQ: '', todayFrom: '', todayTo: '', todayCategory: 'all', doctorStatus: 'all', doctorArea: 'all', searchQ: '', searchSource: '', searchQuestion: '' };
const searchSources = [['','全部来源'], ['personal_memory','personal_memory'], ['mobile','mobile'], ['local_ai','local_ai'], ['report','report'], ['filesystem','filesystem'], ['browser','browser'], ['apple_mail','apple_mail']];
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const escAttr = (s) => String(s ?? '').replace(/\\/g, '\\\\').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/'/g, "\\'").replace(/\n/g, ' ');
const jstr = (s) => JSON.stringify(String(s ?? ''));
const domId = (s) => String(s ?? '').replace(/[^a-zA-Z0-9_-]/g, '_');
const status = (s) => {
  const key = String(s || 'info');
  return `<span class="status ${esc(key)}">${esc(t(key))}</span>`;
};
function askConfirm(message){
  return window.confirm(translateText(message));
}
const sectionTips = {
  action: '行动总览会合并今日重点、处理队列、修复项、项目聚类和说话人质量。',
  inbox: '把录音、快速标注、修复项、项目和说话人待处理集中成一个可清空的处理队列。',
  projects: '按证据自动聚合今天的主题、项目和相关下一步，是行动工作区里的完整项目视图。',
  memory: '把每天的项目聚类和会议结论沉淀为长期项目档案。',
  personal: '维护用户档案、联系人、确认记忆、候选收件箱、冲突和隐私删除。',
  meeting: '开会时记录议程、笔记和行动项，并回写项目记忆与本地时间线。',
  today: '打开实时日内时间线，合并应用、录音、文件、位置和提醒。',
  overview: '查看系统数据量、健康状态、最近采集和维护入口。',
  doctor: '运行本机诊断，检查采集器、同步服务、本地 AI 和数据质量。',
  audio: '查看移动端录音分析队列，并手动触发转写和摘要。',
  'speaker-training': '把样本、embedding、一致性、代表样本、自动整理和人工确认串成一个训练闭环。',
  search: '对本地资料做关键词搜索、语义检索和证据问答。',
  timeline: '查看原始事件流，适合排查某一天的底层记录。',
  reports: '打开日报、长期摘要、邮件摘要和反馈记录。',
  personal: '把个人事实、偏好、边界、联系人和候选记忆沉淀成可追溯的长期档案。',
  sources: '检查各数据来源是否开启、最近是否采集，以及缺少哪些前置文件。',
  speakers: '查看说话人聚类、样本、重命名和合并入口。',
  files: '查看文件监控路径、分析状态，并手动扫描新文件。',
  recycle: '查看分析后暂存的回收文件，预览清理或恢复文件。',
  mobile: '已整合到手机同步页。',
  setup: '按当前机器状态完成首次配置、手机同步 token、Mac 服务和 iPhone 连接地址。',
  privacy: '集中查看敏感来源、保留策略、缓存清理、发布边界和隐私风险。',
  sync: '查看 Mac/手机连接、上传缓存、导入缓存、音频分析、去重和清理预览。',
  maintenance: '统一预览和执行数据库记录、运行日志、缓存和回收箱清理。',
  settings: '查看和编辑当前配置，敏感字段会被隐藏。'
};
const actionTips = {
  collect: '立即采集当天数据，并按配置刷新报告。',
  analyze_audio: '处理待分析录音，生成转写、摘要和说话人线索。',
  refresh_report: '重新生成今天的日报和摘要文件。',
  retention: '预览或执行长期保留策略，清理已压缩的旧数据。',
  email_due: '检查当前是否有到期的邮件摘要。',
  compact: '把当天资料压缩进长期日/周/月记忆。',
  install_agent: '安装或重载 Mac 后台采集 LaunchAgent。',
  install_sync_agent: '安装或重载手机上传接收服务。',
  install_dashboard_agent: '安装或重载桌面 dashboard 服务。',
  search_index: '重建本地语义搜索索引，供问答和相似检索使用。',
  speaker_rename: '把选中的说话人 ID 改成真实显示名。',
  speaker_normalize_names: '把自动生成的局部 Speaker 名整理成稳定的全局 Voice ID。',
  speaker_merge: '把一个说话人合并到另一个说话人。',
  speaker_merge_many: '把多个已勾选的说话人一次合并到同一个目标。',
  speaker_delete: '删除一个说话人及其托管样本记录。',
  speaker_delete_many: '一次删除多个已勾选的说话人及其托管样本记录。',
  speaker_detach_sample: '把这条样本从当前说话人中分离出来，单独新建一个 Voice。',
  speaker_refresh_sample_confidence: '重新计算说话人的 embedding 聚类一致性，并刷新每条样本相对当前聚类的一致性。',
  speaker_repair_sample_clips: '按当前裁剪策略重裁筛选出来的说话人样本，并重新计算变更样本的 embedding。',
  speaker_auto_organize: '按当前配置阈值自动合并相似声音，并隐藏低相似未命名 Voice。',
  speaker_confirm: '确认这些说话人整理结果正确，后续自动整理不会主动隐藏它们。',
  speaker_unhide: '把低相似隐藏 Voice 放回人工复查列表。',
  analyze_new_files: '扫描监控路径里的新文件，并用本地分析流程处理。',
  recycle_purge: '预览或执行回收箱到期清理。',
  recycle_restore: '把回收箱中的文件恢复到原路径或指定路径。',
  mobile_cleanup: '预览或执行移动端上传缓存和无引用导入目录清理。'
};
const labelTips = {
  '采集': '立即更新今天的资料，不等待后台定时采集。',
  '分析音频': '处理今天尚未完成的录音分析。',
  '刷新': '重新读取当前页面的数据。',
  '查找': '按日期、时间段和关键词筛选今天的事件。',
  '写入长期记忆': '把这条反馈保存到数据库、反馈摘要和本地检索资料里。',
  '采集并写报告': '采集今天的数据并刷新今天报告。',
  '刷新今日报告': '基于已有数据重新生成今天报告。',
  '生成新 token': '生成新的手机同步密钥并写入 config.json；旧 iPhone 配置需要同步更新。',
  '安装全部服务': '依次安装并加载同步、后台采集和 dashboard 服务。',
  '复制': '复制这一项到剪贴板。',
  '复制 token': '复制刚生成的新 token。',
  '复制 URL': '复制这个 Mac 同步地址。',
  'Run checks': '重新运行本机诊断。',
  'Run 5': '从音频队列中处理最多 5 条。',
  'Run 20': '从音频队列中处理最多 20 条。',
  '分析 5 条': '从音频队列中处理最多 5 条。',
  '分析 10 条': '从音频队列中处理最多 10 条。',
  '分析 20 条': '从音频队列中处理最多 20 条。',
  '分析 50 条': '从音频队列中处理最多 50 条。',
  '底层时间线': '打开原始事件流，用于排查某一天的底层记录。',
  'Refresh': '重新读取当前页面的数据。',
  'All': '清除当前筛选，显示全部记录。',
  'Index status': '刷新语义索引状态。',
  'Build semantic index': '重建本地 embedding 索引。',
  'Search': '搜索本地 observations、报告和语义索引。',
  'Ask local data': '用本地检索结果向本地模型提问。',
  'Load': '载入指定日期的数据。',
  'Refresh today': '重新生成今天的报告。',
  'Rename': '将指定说话人 ID 重命名。',
  '整理自动名': '把未人工命名的 Speaker 1/2/数字标签改成稳定的 Voice ID。',
  'Merge': '把重复说话人合并到保留 ID。',
  '清空选择': '清空当前勾选的说话人。',
  '选择当前筛选': '勾选当前筛选结果里显示的所有说话人。',
  '反选当前筛选': '切换当前筛选结果里的勾选状态。',
  '合并选中': '把所有已勾选说话人合并到指定目标。',
  '删除选中': '删除所有已勾选说话人、aliases、样本记录和托管样本文件。',
  'Scan now': '立即扫描并分析新文件。',
  'Purge dry-run': '只预览会清理哪些回收文件。',
  'Purge due now': '永久删除已到期的回收文件。',
  'Restore': '恢复选中的回收文件。',
  'Cleanup dry-run': '只预览移动端缓存清理结果。',
  'Apply cleanup': '执行移动端缓存清理。',
  '手机同步': '查看手机同步、Mac 在线状态、上传缓存和音频分析。',
  '记录维护': '统一清理旧事件、运行记录、日志、缓存和回收箱。',
  '记录预览': '预览按保留策略会清理哪些旧数据库记录、报告和日志。',
  '执行记录清理': '按保留策略实际删除旧数据库记录、报告并裁剪过大的日志。',
  '缓存预览': '预览移动端上传缓存和无引用导入目录清理。',
  '执行缓存清理': '执行移动端上传缓存和无引用导入目录清理。',
  '回收箱预览': '预览哪些回收箱文件已经到期。',
  '清理回收箱': '永久删除已经到期的回收箱文件。',
  '诊断': '跳转到诊断页，检查配置关联的采集器、服务和模型。',
  '保留预览': '只预览长期保留策略会清理的内容。',
  '执行保留': '执行长期保留清理策略。',
  'Apply retention': '执行长期保留清理策略。',
  '保存设置': '把当前分组的可编辑配置写入 config.json。',
  '重载 Agent': '重新加载后台采集服务，让采集、音频、文件分析等配置生效。',
  '重载同步服务': '重新加载手机上传接收服务，让端口、上传限制和导入策略生效。',
  '重载 Dashboard': '重新加载桌面 dashboard 服务。'
};
let buttonTipObserver = null;
let activeTipButton = null;
function toast(msg){ const el=$('toast'); el.textContent=translateText(msg); el.classList.add('show'); setTimeout(()=>el.classList.remove('show'), 6500); }
async function api(path, opts){ const r=await fetch(path, opts); const j=await r.json(); if(!r.ok) throw new Error(j.error || r.statusText); return j; }
function hasStoredLanguagePreference(){
  try { return !!localStorage.getItem(languageStorageKey); }
  catch { return false; }
}
async function syncDashboardLanguagePreference(value, opts={}){
  const language = normalizeLanguage(value);
  try {
    await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({updates:[{key:'dashboard.language',value:language}]})});
  } catch(e) {
    if(!opts.silent) toast(`Language sync failed\n${String(e)}`);
  }
}
async function syncDashboardLanguageOnLoad(){
  if(hasStoredLanguagePreference()){
    await syncDashboardLanguagePreference(activeLanguage, {silent:true});
    return;
  }
  try {
    const j = await api('/api/settings');
    const serverLanguage = normalizeLanguage((((j.settings || {}).dashboard || {}).language) || activeLanguage);
    if(serverLanguage !== activeLanguage){
      activeLanguage = serverLanguage;
      state.language = activeLanguage;
      try { localStorage.setItem(languageStorageKey, activeLanguage); } catch {}
      nav();
      await render();
      localizeDocument();
      return;
    }
  } catch {}
  await syncDashboardLanguagePreference(activeLanguage, {silent:true});
}
function canonicalSection(id){ return id === 'mobile' ? 'sync' : (id === 'suggestions' ? 'inbox' : (id || 'today')); }
function isKnownSection(id){ return allSections.some(s=>s[0]===id); }
function nav(){
  const groups = [];
  sections.forEach(([id,label]) => {
    const group = sectionGroups[id] || '其他';
    let bucket = groups.find(item => item.name === group);
    if(!bucket){ bucket = {name: group, items: []}; groups.push(bucket); }
    bucket.items.push([id,label]);
  });
  $('nav').innerHTML = groups.map(group => `<div class="nav-group"><div class="nav-label">${esc(t(group.name))}</div>${group.items.map(([id,label]) => {
    const active = state.section === id || navParents[state.section] === id;
    return `<button class="${active?'active':''}" onclick="go('${id}')">${esc(t(label))}</button>`;
  }).join('')}</div>`).join('');
}
function sectionNav(sectionId=state.section){
  const parent = navParents[sectionId] || sectionId;
  const tabs = sectionTabs[parent] || [];
  if(!tabs.length) return '';
  return `<div class="section-tabs">${tabs.map(([id,label]) => {
    const active = state.section === id;
    return `<button class="filter-pill ${active?'active':''}" onclick="go('${id}')">${esc(t(label))}</button>`;
  }).join('')}</div>`;
}
function setHeader(title, subtitle='', buttons=''){
  hideButtonTip();
  $('title').textContent=translateText(title);
  $('subtitle').textContent=translateText(subtitle);
  $('toolbar').innerHTML=`${sectionNav()}${buttons}`;
  localizeElement($('toolbar'));
  applyButtonTips($('toolbar'));
  nav();
}
async function action(name,args={}){ const j=await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,args})}); toast(`${j.ok?'OK':'FAILED'} ${name}\n${j.stdout || j.stderr || ''}`); render(); }
async function go(id){ state.section=canonicalSection(id); history.replaceState(null,'','#'+state.section); render(); }
function metrics(items){ return `<div class="grid cols-4">${items.map(x=>`<div class="card metric"><div class="label">${esc(x[0])}</div><div class="value">${esc(x[1])}</div><div class="hint">${esc(x[2]||'')}</div></div>`).join('')}</div>`; }
function startButtonTips(){
  applyButtonTips(document);
  document.addEventListener('mouseover', onTipEnter);
  document.addEventListener('focusin', onTipEnter);
  document.addEventListener('mousemove', onTipMove);
  document.addEventListener('mouseout', onTipLeave);
  document.addEventListener('focusout', onTipLeave);
  document.addEventListener('keydown', (event) => { if(event.key === 'Escape') hideButtonTip(); });
  if(window.MutationObserver && !buttonTipObserver){
    buttonTipObserver = new MutationObserver(() => applyButtonTips(document));
    buttonTipObserver.observe(document.body, { childList: true, subtree: true });
  }
}
function applyButtonTips(root=document){
  const buttons = root && root.matches && root.matches('button') ? [root] : Array.from((root || document).querySelectorAll ? (root || document).querySelectorAll('button') : []);
  buttons.forEach(button => {
    const sourceTip = button.dataset.tipSource || inferButtonTip(button);
    if(!sourceTip) return;
    button.dataset.tipSource = sourceTip;
    const tip = translateText(sourceTip);
    const label = translateText(buttonText(button));
    if(button.dataset.tip !== tip) button.dataset.tip = tip;
    if(button.getAttribute('aria-label') !== `${label}: ${tip}`) button.setAttribute('aria-label', `${label}: ${tip}`);
    if(button.getAttribute('title') !== tip) button.setAttribute('title', tip);
    button.classList.add('has-tip');
  });
}
function inferButtonTip(button){
  const explicit = button.getAttribute('data-tip-source') || button.getAttribute('data-tip');
  if(explicit) return explicit;
  const click = button.getAttribute('onclick') || '';
  const goMatch = click.match(/go\('([^']+)'\)/);
  if(goMatch && sectionTips[goMatch[1]]) return sectionTips[goMatch[1]];
  const actionMatch = click.match(/action\('([^']+)'/);
  if(actionMatch && actionTips[actionMatch[1]]) return actionTips[actionMatch[1]];
  if(click.includes('restoreRecycle')) return actionTips.recycle_restore;
  if(click.includes('refreshSpeakerSampleConfidence') || click.includes('refreshSelectedSpeakerSampleConfidence')) return actionTips.speaker_refresh_sample_confidence;
  if(click.includes('refreshVisibleSpeakerSampleConfidence')) return actionTips.speaker_refresh_sample_confidence;
  if(click.includes('refreshFocusedSampleSpeakerConfidence')) return actionTips.speaker_refresh_sample_confidence;
  if(click.includes('autoOrganizeSpeakers')) return actionTips.speaker_auto_organize;
  if(click.includes('confirmSelectedSpeakers')) return actionTips.speaker_confirm;
  if(click.includes('confirmVisibleSpeakers')) return actionTips.speaker_confirm;
  if(click.includes('unhideSelectedSpeakers')) return actionTips.speaker_unhide;
  if(click.includes('unhideVisibleSpeakers')) return actionTips.speaker_unhide;
  if(click.includes('submitFeedback')) return labelTips['写入长期记忆'];
  if(click.includes('doSearch')) return labelTips.Search;
  if(click.includes('doAsk')) return labelTips['Ask local data'];
  if(click.includes('refreshSearchIndex')) return labelTips['Index status'];
  if(click.includes('state.todayDate')) return labelTips['查找'];
  if(click.includes('state.timelineDate')) return labelTips.Load;
  if(click.includes('state.audioStatus')) return '按这个状态筛选音频队列。';
  const text = buttonText(button);
  return labelTips[text] || null;
}
function buttonText(button){ return button.textContent.replace(/\s+/g, ' ').trim(); }
function onTipEnter(event){
  const button = event.target.closest && event.target.closest('button[data-tip]');
  if(!button) return;
  activeTipButton = button;
  showButtonTip(button, event);
}
function onTipMove(event){
  if(!activeTipButton) return;
  positionButtonTip(event.clientX, event.clientY);
}
function onTipLeave(event){
  const button = event.target.closest && event.target.closest('button[data-tip]');
  if(!button || button !== activeTipButton) return;
  if(event.relatedTarget && button.contains(event.relatedTarget)) return;
  hideButtonTip();
}
function showButtonTip(button, event){
  const el = $('buttonTooltip');
  el.textContent = button.dataset.tip || '';
  if(!el.textContent) return;
  el.classList.add('show');
  const rect = button.getBoundingClientRect();
  positionButtonTip(event.clientX || rect.left + rect.width / 2, event.clientY || rect.bottom);
}
function hideButtonTip(){
  activeTipButton = null;
  const el = $('buttonTooltip');
  if(el) el.classList.remove('show');
}
function positionButtonTip(x, y){
  const el = $('buttonTooltip');
  if(!el || !el.classList.contains('show')) return;
  const margin = 12;
  const rect = el.getBoundingClientRect();
  let left = x + margin;
  let top = y + margin;
  if(left + rect.width > window.innerWidth - margin) left = Math.max(margin, window.innerWidth - rect.width - margin);
  if(top + rect.height > window.innerHeight - margin) top = Math.max(margin, y - rect.height - margin);
  el.style.left = `${left}px`;
  el.style.top = `${top}px`;
}
let localizationObserver = null;
let localizationScheduled = false;
let localizationActive = false;
const i18nAttributeNames = ['placeholder', 'title', 'aria-label'];
const i18nSkipSelector = [
  'pre',
  'code',
  '.settings-pre',
  '.report-reader-content',
  '.result-text',
  '.event-title',
  '.event-body',
  '.timeline-title',
  '.timeline-body',
  '.file-title',
  '.file-body',
  '.audio-title',
  '.audio-body',
  '.sync-title',
  '.sync-body',
  '.mobile-title',
  '.memory-title',
  '.memory-body',
  '.meeting-title',
  '.meeting-body',
  '.speaker-name',
  '.speaker-transcript',
  '.privacy-note',
  '.source-name',
  '.source-issue-body',
  '.check-message',
  '.fix-command',
  '.setup-url',
  '.setup-token-value',
  '.mono'
].join(',');
function startLocalization(){
  setDocumentLanguage();
  localizeDocument();
  if(localizationObserver) return;
  localizationObserver = new MutationObserver(scheduleLocalization);
  localizationObserver.observe(document.body, {childList:true, subtree:true, characterData:true, attributes:true, attributeFilter:i18nAttributeNames});
}
function scheduleLocalization(){
  if(localizationActive || localizationScheduled) return;
  localizationScheduled = true;
  queueMicrotask(() => {
    localizationScheduled = false;
    localizeDocument();
  });
}
function localizeDocument(){
  if(localizationActive) return;
  localizationActive = true;
  try {
    setDocumentLanguage();
    if(document.body){
      localizeElement(document.body);
      applyButtonTips(document);
    }
  } finally {
    localizationActive = false;
  }
}
function localizeElement(root){
  if(!root) return;
  if(root.nodeType === Node.TEXT_NODE){
    localizeTextNode(root);
    return;
  }
  if(root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_NODE) return;
  const element = root.nodeType === Node.ELEMENT_NODE ? root : null;
  if(element){
    localizeAttributes(element);
    if(shouldSkipI18n(element)) return;
  }
  Array.from(root.childNodes || []).forEach(localizeElement);
}
function shouldSkipI18n(element){
  return !!(element && element.closest && element.closest(i18nSkipSelector));
}
function localizeTextNode(node){
  const parent = node.parentElement;
  if(!parent || shouldSkipI18n(parent)) return;
  const current = node.nodeValue || '';
  if(!current.trim()) return;
  if(node.__i18nSource === undefined || current !== node.__i18nRendered){
    node.__i18nSource = current;
  }
  const rendered = translateText(node.__i18nSource);
  node.__i18nRendered = rendered;
  if(current !== rendered) node.nodeValue = rendered;
}
function localizeAttributes(element){
  i18nAttributeNames.forEach(attr => {
    if(!element.hasAttribute(attr)) return;
    const current = element.getAttribute(attr) || '';
    if(!current.trim()) return;
    const sourceKey = `__i18n_${attr}_source`;
    const renderedKey = `__i18n_${attr}_rendered`;
    if(element[sourceKey] === undefined || current !== element[renderedKey]){
      element[sourceKey] = current;
    }
    const rendered = translateText(element[sourceKey]);
    element[renderedKey] = rendered;
    if(current !== rendered) element.setAttribute(attr, rendered);
  });
}
function languageOptions(){
  return supportedLanguages.map(([code,label]) => `<option value="${escAttr(code)}" ${currentLanguage()===code?'selected':''}>${esc(label)}</option>`).join('');
}
function setLanguage(value){
  activeLanguage = normalizeLanguage(value);
  state.language = activeLanguage;
  try { localStorage.setItem(languageStorageKey, activeLanguage); } catch {}
  syncDashboardLanguagePreference(activeLanguage, {silent:false});
  hideButtonTip();
  render().then(() => localizeDocument()).catch(e => toast(String(e)));
}
async function actionCenter(){
  const buttons = `<button class="btn" onclick="action('collect',{date:'today'})">采集</button><button class="btn" onclick="action('analyze_audio',{date:${jstr(state.actionDate || 'today')},limit:20})">分析音频</button><button class="btn" onclick="go('inbox')">处理队列</button><button class="btn primary" onclick="actionCenter()">刷新</button>`;
  setHeader('行动总览','读取中...', buttons);
  const [center, inbox, quality] = await Promise.all([
    api(`/api/action-center?date=${encodeURIComponent(state.actionDate || 'today')}`),
    api(`/api/action-inbox?date=${encodeURIComponent(state.actionDate || 'today')}&status=active`),
    api('/api/speaker-quality?view=needs_work')
  ]);
  const summary = center.summary || {};
  const inboxSummary = inbox.summary || {};
  const qualitySummary = quality.summary || {};
  const inboxRows = inbox.items || [];
  $('subtitle').textContent = `${center.date || ''} · ${inboxRows.length} 待处理 · ${summary.priority_repairs || 0} 待修复 · ${summary.projects || 0} 项目`;
  $('view').innerHTML = `
    <div class="action-hero">
      <section class="card">
        <div class="section-title"><h3>行动总览</h3><span class="muted">${esc(shortDateTime(center.generated_at || ''))}</span></div>
        <div class="action-toolbar">
          <input value="${escAttr(state.actionDate || 'today')}" onchange="state.actionDate=this.value || 'today'; actionCenter()" placeholder="today / yesterday / YYYY-MM-DD">
        </div>
        <div class="action-kpis" style="margin-top:12px">
          ${actionKpi('待处理', inboxRows.length, `${inboxSummary.high || 0} high`)}
          ${actionKpi('待修复', summary.priority_repairs || 0, 'critical / warn')}
          ${actionKpi('今日证据', summary.observations || 0, `${summary.activity_samples || 0} app samples`)}
          ${actionKpi('Speaker', qualitySummary.needs_work || 0, `avg ${qualitySummary.average_score || 0}`)}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>快速流转</h3><span class="muted">可执行</span></div>
        <div class="overview-actions">
          <button class="btn primary" onclick="go('inbox')">打开处理队列</button>
          <button class="btn" onclick="runFirstRepair()">执行第一条修复</button>
          <button class="btn" onclick="go('projects')">项目聚类</button>
          <button class="btn" onclick="go('search')">证据问答</button>
          <button class="btn" onclick="go('today')">今天时间线</button>
          <button class="btn" onclick="action('refresh_report',{date:state.actionDate || 'today'})">刷新日报</button>
        </div>
        <div class="quick-tag-row">${quickTagChips(center.quick_tags || [])}</div>
      </section>
    </div>
    <div class="action-main">
      <div class="action-stack">
        <section class="card">
          <div class="section-title"><h3>处理队列摘要</h3><span class="muted">${esc(inboxRows.length)} active</span></div>
          ${actionInboxList(inboxRows.slice(0, 10), {compact:true})}
          ${inboxRows.length > 10 ? `<div class="search-actions" style="margin-top:10px"><button class="btn" onclick="go('inbox')">查看全部 ${esc(inboxRows.length)} 条</button></div>` : ''}
        </section>
        <section class="card">
          <div class="section-title"><h3>待修复队列</h3><span class="muted">${esc((center.repair_queue || []).length)} items</span></div>
          ${repairList(center.repair_queue || [])}
        </section>
        <section class="card">
          <div class="section-title"><h3>项目 / 主题聚类</h3><span class="muted">${esc((center.projects || []).length)} clusters</span></div>
          ${projectList(center.projects || [])}
        </section>
      </div>
      <div class="action-side">
        <section class="card">
          <div class="section-title"><h3>今日重点</h3><span class="muted">${esc((center.highlights || []).length)} highlights</span></div>
          ${highlightList(center.highlights || [])}
        </section>
        <section class="card">
          <div class="section-title"><h3>说话人质量</h3><span class="muted">${esc(qualitySummary.needs_work || 0)} need work</span></div>
          ${qualityList(quality.speakers || [])}
        </section>
      </div>
    </div>`;
  window.__actionCenterData = center;
  window.__inboxItems = inboxRows;
}
function actionKpi(label, value, hint){
  return `<div class="action-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function repairList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有需要处理的修复项</div>';
  return `<div class="repair-list">${rows.map(repairCard).join('')}</div>`;
}
function repairCard(item){
  const actionButton = item.action ? `<button class="btn primary" data-action="${escAttr(JSON.stringify(item.action))}" onclick="runCardAction(this)">${esc(item.action.label || '执行')}</button>` : '';
  return `<div class="repair-card ${esc(item.severity || 'info')}">
    <div class="repair-top"><div><div class="repair-title">${esc(item.title || item.id)}</div><div class="item-meta">${esc(item.area || '')}</div></div>${status(item.severity || 'info')}</div>
    <div class="repair-body">${esc(item.body || '')}</div>
    ${evidenceChips(item.evidence || [])}
    ${actionButton ? `<div class="search-actions" style="margin-top:10px">${actionButton}</div>` : ''}
  </div>`;
}
function suggestionList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有检测到新的行动建议</div>';
  return `<div class="suggestion-list">${rows.map(item => `<div class="suggestion-card">
    <div class="suggestion-top"><div><div class="suggestion-title">${esc(item.title)}</div><div class="item-meta">${esc(shortDateTime(item.observed_at || ''))} · ${esc(item.source || '')}/${esc(item.kind || '')}</div></div>${status(item.priority)}</div>
    <div class="suggestion-body">${esc(item.body || '')}</div>
    <div class="project-keywords"><span class="evidence-chip">${esc((item.recommended_action || {}).label || '稍后处理')}</span><span class="evidence-chip">${esc(item.reason || '')}</span></div>
  </div>`).join('')}</div>`;
}
function projectList(rows){
  if(!(rows || []).length) return '<div class="empty-state">今天还没有形成明显项目聚类</div>';
  return `<div class="project-list">${rows.map(item => `<div class="project-card">
    <div class="project-top"><div><div class="project-title">${esc(item.title)}</div><div class="item-meta">${esc(shortDateTime((item.time_span || {}).start || ''))} -> ${esc(shortDateTime((item.time_span || {}).end || ''))}</div></div><span class="status ok">${esc(Math.round(Number(item.confidence || 0) * 100))}%</span></div>
    <div class="project-body">${esc(item.summary || '')}</div>
    <div class="project-keywords">${(item.keywords || []).map(keyword => `<span class="evidence-chip">${esc(keyword)}</span>`).join('')}</div>
    ${evidenceChips(item.evidence || [])}
  </div>`).join('')}</div>`;
}
function qualityList(rows){
  if(!(rows || []).length) return '<div class="empty-state">说话人质量目前没有明显待处理项</div>';
  return `<div class="quality-list">${rows.slice(0, 6).map(item => `<div class="quality-card">
    <div class="quality-top"><div><div class="quality-title">${esc(item.display_name)}</div><div class="item-meta">${esc(item.sample_count)} samples · ${esc(item.day_count)} days · ${esc(item.identity_status)}</div></div><span class="status ${item.score >= 75 ? 'ok' : 'warn'}">${esc(item.score)}</span></div>
    <div class="quality-meter ${esc(item.grade)}"><span style="width:${Math.max(0, Math.min(100, Number(item.score || 0)))}%"></span></div>
    <div class="quality-issues">${(item.issues || []).map(issue => `<span class="evidence-chip">${esc(issue.label || issue.kind)}</span>`).join('') || '<span class="evidence-chip">无明显问题</span>'}</div>
    <div class="search-actions" style="margin-top:8px">${(item.recommendations || []).slice(0,2).map(rec => `<button class="btn" data-action="${escAttr(JSON.stringify({name:rec.action,args:rec.args || {},label:rec.label}))}" onclick="runCardAction(this)">${esc(rec.label)}</button>`).join('')}</div>
  </div>`).join('')}</div>`;
}
function highlightList(rows){
  if(!(rows || []).length) return '<div class="empty-state">今天还没有可展示重点</div>';
  return `<div class="highlight-list">${rows.slice(0, 10).map(item => `<div class="highlight-card">
    <div class="highlight-top"><div><div class="highlight-title">${esc(item.title || item.kind)}</div><div class="item-meta">${esc(shortDateTime(item.time || ''))} · ${esc(item.source || '')}/${esc(item.kind || '')}</div></div><span class="category ${esc(item.category || 'other')}">${esc(item.category || 'other')}</span></div>
    <div class="highlight-body">${esc(item.body || '')}</div>
  </div>`).join('')}</div>`;
}
function quickTagChips(rows){
  if(!(rows || []).length) return '<span class="evidence-chip">暂无手机快速标注</span>';
  return rows.slice(0, 10).map(item => `<span class="evidence-chip">${esc(item.tag || item.title)} · ${esc(shortDateTime(item.time || ''))}</span>`).join('');
}
function evidenceChips(rows){
  if(!(rows || []).length) return '';
  return `<div class="repair-evidence">${rows.slice(0, 6).map(item => `<span class="evidence-chip">${esc(item.title || item.time || item.path || item.id || item.status || 'evidence')}</span>`).join('')}</div>`;
}
async function runCardAction(button){
  const payload = JSON.parse(button.dataset.action || '{}');
  if(!payload.name) return;
  await action(payload.name, payload.args || {});
}
function runFirstRepair(){
  const rows = (window.__actionCenterData || {}).repair_queue || [];
  const item = rows.find(row => row.action);
  if(!item) return toast('没有可执行的修复项');
  action(item.action.name, item.action.args || {});
}
async function actionInbox(){
  const buttons = `<button class="btn" onclick="setInboxDate('today')">今天</button><button class="btn" onclick="setInboxDate('yesterday')">昨天</button><button class="btn" onclick="bulkInboxState('done')">当前完成</button><button class="btn" onclick="go('action')">行动总览</button><button class="btn primary" onclick="actionInbox()">刷新</button>`;
  setHeader('处理队列','读取中...', buttons);
  const params = new URLSearchParams({date: state.inboxDate || 'today', status: state.inboxStatus || 'active'});
  if(state.inboxQ) params.set('q', state.inboxQ);
  if(state.inboxPriority && state.inboxPriority !== 'all') params.set('priority', state.inboxPriority);
  if(state.inboxSource && state.inboxSource !== 'all') params.set('source', state.inboxSource);
  if(state.inboxType && state.inboxType !== 'all') params.set('type', state.inboxType);
  const j = await api('/api/action-inbox?' + params.toString());
  const summary = j.summary || {};
  const stateSummary = summary.state || {};
  const rows = j.items || [];
  window.__inboxItems = rows;
  $('subtitle').textContent = `${j.date || ''} · ${rows.length}/${summary.all || rows.length} 条 · ${insightStatusLabel(state.inboxStatus)}`;
  $('view').innerHTML = `
    <div class="insight-hero">
      <section class="card">
        <div class="section-title"><h3>行动处理队列</h3><span class="muted">${esc(shortDateTime(j.generated_at || ''))}</span></div>
        <div class="insight-toolbar inbox-toolbar">
          <input id="inboxDate" value="${escAttr(state.inboxDate || 'today')}" aria-label="date">
          <input id="inboxQ" value="${escAttr(state.inboxQ || '')}" placeholder="搜索行动、来源、证据" onkeydown="inboxKey(event)" aria-label="search">
          <select id="inboxType">${inboxTypeOptions(state.inboxType)}</select>
          <select id="inboxPriority">${suggestionPriorityOptions(state.inboxPriority)}</select>
          <select id="inboxSource">${insightSourceOptions(state.inboxSource)}</select>
          <button class="btn primary" onclick="applyInboxFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">${inboxStatusPills(state.inboxStatus, summary)}</div>
        <div class="insight-kpis">
          ${insightKpi('当前', rows.length, 'current filter')}
          ${insightKpi('未处理', stateSummary.open || 0, 'open')}
          ${insightKpi('高优先级', summary.high || 0, 'high')}
          ${insightKpi('可执行', summary.ready_actions || 0, 'actions')}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>处理流</h3><span class="muted">清空队列</span></div>
        <div class="overview-actions">
          <button class="btn" onclick="go('action')">行动总览</button>
          <button class="btn" onclick="go('today')">今天时间线</button>
          <button class="btn" onclick="bulkInboxState('snoozed')">当前稍后</button>
          <button class="btn danger" onclick="bulkInboxState('dismissed')">当前忽略</button>
        </div>
        ${inboxTypeBreakdown(summary)}
      </section>
    </div>
    <div class="insight-main">
      <section class="card">
        <div class="section-title"><h3>队列列表</h3><span class="muted">${esc(rows.length)} shown</span></div>
        ${actionInboxList(rows)}
      </section>
      <aside class="insight-side">
        <section class="card">
          <div class="section-title"><h3>类型</h3><span class="muted">${esc(state.inboxType || 'all')}</span></div>
          <div class="quickbar">${inboxTypePills(summary)}</div>
        </section>
        <section class="card">
          <div class="section-title"><h3>优先级</h3><span class="muted">${esc(priorityLabel(state.inboxPriority || 'all'))}</span></div>
          <div class="quickbar">${inboxPriorityPills(summary)}</div>
        </section>
        <section class="card">
          <div class="section-title"><h3>状态</h3></div>
          ${insightStateBreakdown(summary)}
        </section>
      </aside>
    </div>`;
}
function actionInboxList(rows, opts={}){
  if(!(rows || []).length) return '<div class="empty-state">当前没有待处理行动</div>';
  return `<div class="insight-list action-inbox-list">${rows.map(item => inboxCard(item, opts)).join('')}</div>`;
}
function inboxCard(item, opts={}){
  const stateInfo = item.state || {};
  const currentStatus = stateInfo.status || 'open';
  const pinned = !!stateInfo.pinned;
  const itemType = item.item_type || 'suggestion';
  const actionButton = item.action ? `<button class="btn primary" data-action="${escAttr(JSON.stringify(item.action))}" onclick="runCardAction(this)">${esc(item.action.label || '执行')}</button>` : '';
  const compact = !!opts.compact;
  return `<article class="insight-card inbox-card ${esc(item.inbox_type || '')} ${esc(item.priority || 'low')} ${esc(currentStatus)}">
    <div class="insight-head">
      <div>
        <div class="insight-title">${pinned ? '★ ' : ''}${esc(item.title || 'Action')}</div>
        <div class="item-meta">${esc(shortDateTime(item.time || ''))} · ${esc(inboxTypeLabel(item.inbox_type))} · ${esc(item.reason || '')}</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${status(item.priority || 'low')}${status(currentStatus)}</div>
    </div>
    <div class="insight-body">${esc(item.body || '')}</div>
    <div class="insight-chips">
      <span class="evidence-chip">${esc((item.recommended_action || {}).label || '稍后处理')}</span>
      <span class="evidence-chip">${esc(item.source || '')}/${esc(item.kind || '')}</span>
    </div>
    <div class="insight-actions">
      ${actionButton}
      <button class="btn" data-item-id="${escAttr(item.id)}" data-item-type="${escAttr(itemType)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInboxItemState(this,'done')">完成</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-item-type="${escAttr(itemType)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInboxItemState(this,'snoozed')">稍后</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-item-type="${escAttr(itemType)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="toggleInboxPin(this)">${pinned ? '取消置顶' : '置顶'}</button>
      <button class="btn" data-query="${escAttr(item.title || item.body || '')}" onclick="openInsightSearch(this)">问证据</button>
      <button class="btn danger" data-item-id="${escAttr(item.id)}" data-item-type="${escAttr(itemType)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInboxItemState(this,'dismissed')">忽略</button>
    </div>
    ${compact ? '' : `<div class="insight-note">
      <textarea data-insight-note placeholder="处理备注">${esc(stateInfo.note || '')}</textarea>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-item-type="${escAttr(itemType)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="saveInboxItemNote(this)">保存备注</button>
    </div>
    ${insightEvidenceDetails(item.evidence || [])}`}
  </article>`;
}
function inboxTypeOptions(current){
  return inboxTypeRows().map(([value,label]) => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(label)}</option>`).join('');
}
function inboxTypeRows(){
  return [['all','全部类型'], ['suggestion','建议'], ['quick_tag','快速标注'], ['repair','修复'], ['project','项目'], ['speaker','说话人']];
}
function inboxTypeLabel(value){
  const row = inboxTypeRows().find(item => item[0] === value);
  return row ? row[1] : (value || '类型');
}
function inboxTypePills(summary){
  const counts = (summary || {}).by_type_all || (summary || {}).by_type || {};
  return inboxTypeRows().map(([value,label]) => {
    const count = value === 'all' ? ((summary || {}).all || 0) : (counts[value] || 0);
    return `<button class="filter-pill ${state.inboxType===value?'active':''}" onclick="setInboxType('${value}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`;
  }).join('');
}
function inboxTypeBreakdown(summary){
  const counts = (summary || {}).by_type_all || {};
  const rows = inboxTypeRows().filter(([value]) => value !== 'all');
  return `<div class="insight-state-list" style="margin-top:12px">${rows.map(([key,label]) => `<div class="insight-state-row"><span>${esc(label)}</span><span class="queue-value">${esc(counts[key] || 0)}</span></div>`).join('')}</div>`;
}
function inboxStatusPills(current, summary){
  const stateSummary = (summary || {}).state || {};
  const total = Number((summary || {}).all || (summary || {}).total || 0);
  const rows = [
    ['active', '活跃', stateSummary.active ?? total],
    ['open', '未处理', stateSummary.open || 0],
    ['snoozed', '稍后', stateSummary.snoozed || 0],
    ['done', '已完成', stateSummary.done || 0],
    ['dismissed', '已忽略', stateSummary.dismissed || 0],
    ['all', '全部', total],
  ];
  return rows.map(([key, label, count]) => `<button class="filter-pill ${current===key?'active':''}" onclick="setInboxStatus('${key}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function inboxPriorityPills(summary){
  const rows = [['all','全部', (summary || {}).total || 0], ['high','高', (summary || {}).high || 0], ['medium','中', (summary || {}).medium || 0], ['low','低', (summary || {}).low || 0]];
  return rows.map(([key,label,count]) => `<button class="filter-pill ${state.inboxPriority===key?'active':''}" onclick="setInboxPriority('${key}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function applyInboxFilters(){
  state.inboxDate = $('inboxDate').value || 'today';
  state.inboxQ = $('inboxQ').value;
  state.inboxType = $('inboxType').value || 'all';
  state.inboxPriority = $('inboxPriority').value || 'all';
  state.inboxSource = $('inboxSource').value || 'all';
  actionInbox();
}
function inboxKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyInboxFilters();
  }
}
function setInboxDate(value){ state.inboxDate = value || 'today'; actionInbox(); }
function setInboxStatus(value){ state.inboxStatus = value || 'active'; actionInbox(); }
function setInboxType(value){ state.inboxType = value || 'all'; actionInbox(); }
function setInboxPriority(value){ state.inboxPriority = value || 'all'; actionInbox(); }
function setInboxItemState(button, statusValue, pinnedValue){
  setInsightState(button, button.dataset.itemType || 'suggestion', statusValue, pinnedValue);
}
function toggleInboxPin(button){
  const pinned = !(button.dataset.pinned === 'true');
  setInboxItemState(button, button.dataset.status || 'open', pinned);
}
function saveInboxItemNote(button){
  setInboxItemState(button, button.dataset.status || 'open', button.dataset.pinned === 'true');
}
async function bulkInboxState(statusValue){
  const items = window.__inboxItems || [];
  if(!items.length) return toast('当前处理队列为空');
  for(const item of items){
    await api('/api/insight-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:item.id,item_type:item.item_type || 'suggestion',status:statusValue})});
  }
  toast(`已更新 ${items.length} 条`);
  render();
}
async function suggestionInbox(){
  const buttons = `<button class="btn" onclick="setSuggestionDate('today')">今天</button><button class="btn" onclick="setSuggestionDate('yesterday')">昨天</button><button class="btn" onclick="bulkInsightState('suggestion','done')">当前完成</button><button class="btn primary" onclick="suggestionInbox()">刷新</button>`;
  setHeader('行动建议','读取中...', buttons);
  const params = new URLSearchParams({date: state.suggestionDate || 'today', status: state.suggestionStatus || 'active'});
  if(state.suggestionQ) params.set('q', state.suggestionQ);
  if(state.suggestionPriority && state.suggestionPriority !== 'all') params.set('priority', state.suggestionPriority);
  if(state.suggestionSource && state.suggestionSource !== 'all') params.set('source', state.suggestionSource);
  const j = await api('/api/action-suggestions?' + params.toString());
  const summary = j.summary || {};
  const stateSummary = summary.state || {};
  const rows = j.suggestions || [];
  window.__suggestionItems = rows;
  $('subtitle').textContent = `${j.date || ''} · ${rows.length}/${summary.all || rows.length} 条 · ${insightStatusLabel(state.suggestionStatus)}`;
  $('view').innerHTML = `
    <div class="insight-hero">
      <section class="card">
        <div class="section-title"><h3>行动建议收件箱</h3><span class="muted">${esc(shortDateTime(j.generated_at || ''))}</span></div>
        <div class="insight-toolbar">
          <input id="suggestionDate" value="${escAttr(state.suggestionDate || 'today')}" aria-label="date">
          <input id="suggestionQ" value="${escAttr(state.suggestionQ || '')}" placeholder="搜索建议、来源、证据" onkeydown="suggestionKey(event)" aria-label="search">
          <select id="suggestionPriority">${suggestionPriorityOptions(state.suggestionPriority)}</select>
          <select id="suggestionSource">${insightSourceOptions(state.suggestionSource)}</select>
          <button class="btn primary" onclick="applySuggestionFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">${insightStatusPills('suggestion', state.suggestionStatus, summary)}</div>
        <div class="insight-kpis">
          ${insightKpi('当前', rows.length, 'current filter')}
          ${insightKpi('未处理', stateSummary.open || 0, 'open')}
          ${insightKpi('高优先级', summary.high || 0, 'high')}
          ${insightKpi('置顶', stateSummary.pinned || summary.pinned || 0, 'pinned')}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>处理流</h3><span class="muted">stateful</span></div>
        <div class="overview-actions">
          <button class="btn" onclick="go('action')">行动总览</button>
          <button class="btn" onclick="go('projects')">项目聚类</button>
          <button class="btn" onclick="bulkInsightState('suggestion','snoozed')">当前稍后</button>
          <button class="btn danger" onclick="bulkInsightState('suggestion','dismissed')">当前忽略</button>
        </div>
        ${insightStateBreakdown(summary)}
      </section>
    </div>
    <div class="insight-main">
      <section class="card">
        <div class="section-title"><h3>建议列表</h3><span class="muted">${esc(rows.length)} shown</span></div>
        ${suggestionInboxList(rows)}
      </section>
      <aside class="insight-side">
        <section class="card">
          <div class="section-title"><h3>优先级</h3><span class="muted">${esc(state.suggestionPriority || 'all')}</span></div>
          <div class="quickbar">${suggestionPriorityPills(summary)}</div>
        </section>
        <section class="card">
          <div class="section-title"><h3>状态</h3></div>
          ${insightStateBreakdown(summary)}
        </section>
      </aside>
    </div>`;
}
function suggestionInboxList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有匹配的行动建议</div>';
  return `<div class="insight-list">${rows.map(suggestionInboxCard).join('')}</div>`;
}
function suggestionInboxCard(item){
  const stateInfo = item.state || {};
  const currentStatus = stateInfo.status || 'open';
  const pinned = !!stateInfo.pinned;
  return `<article class="insight-card ${esc(item.priority || 'low')} ${esc(currentStatus)}">
    <div class="insight-head">
      <div>
        <div class="insight-title">${pinned ? '★ ' : ''}${esc(item.title || '行动建议')}</div>
        <div class="item-meta">${esc(shortDateTime(item.observed_at || ''))} · ${esc(item.source || '')}/${esc(item.kind || '')} · ${esc(item.reason || '')}</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${status(item.priority || 'low')}${status(currentStatus)}</div>
    </div>
    <div class="insight-body">${esc(item.body || '')}</div>
    <div class="insight-chips">
      <span class="evidence-chip">${esc((item.recommended_action || {}).label || '稍后处理')}</span>
      <span class="evidence-chip">${esc(item.evidence_ref || item.id)}</span>
    </div>
    <div class="insight-actions">
      <button class="btn primary" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'suggestion','done')">完成</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'suggestion','snoozed')">稍后</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="toggleInsightPin(this,'suggestion')">${pinned ? '取消置顶' : '置顶'}</button>
      <button class="btn" data-query="${escAttr(item.title || item.body || '')}" onclick="openInsightSearch(this)">问证据</button>
      <button class="btn danger" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'suggestion','dismissed')">忽略</button>
    </div>
    <div class="insight-note">
      <textarea data-insight-note placeholder="处理备注">${esc(stateInfo.note || '')}</textarea>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="saveInsightNote(this,'suggestion')">保存备注</button>
    </div>
    ${insightEvidenceDetails(item.evidence || [])}
  </article>`;
}
async function projectMemory(){
  const buttons = `<button class="btn" onclick="setMemoryDate('today')">今天</button><button class="btn" onclick="go('meeting')">会议</button><button class="btn" onclick="go('projects')">项目聚类</button><button class="btn primary" onclick="projectMemory()">刷新</button>`;
  setHeader('项目记忆','读取中...', buttons);
  const params = new URLSearchParams({date: state.memoryDate || 'today', status: state.memoryStatus || 'active'});
  if(state.memoryQ) params.set('q', state.memoryQ);
  const j = await api('/api/project-memory?' + params.toString());
  const summary = j.summary || {};
  const memories = j.memories || [];
  const suggested = j.suggested_projects || [];
  window.__projectMemories = memories;
  window.__suggestedProjects = suggested;
  $('subtitle').textContent = `${summary.shown || 0}/${summary.total || 0} 项目 · ${summary.suggested || 0} 今日建议 · ${summary.active_meeting || 0} active meeting`;
  $('view').innerHTML = `
    <div class="insight-hero">
      <section class="card">
        <div class="section-title"><h3>长期项目档案</h3><span class="muted">${esc(shortDateTime(j.generated_at || ''))}</span></div>
        <div class="insight-toolbar projects">
          <input id="memoryDate" value="${escAttr(state.memoryDate || 'today')}" aria-label="date">
          <input id="memoryQ" value="${escAttr(state.memoryQ || '')}" placeholder="搜索项目、关键词、行动项" onkeydown="memoryKey(event)" aria-label="search">
          <select id="memoryStatus">${memoryStatusOptions(state.memoryStatus)}</select>
          <button class="btn primary" onclick="applyMemoryFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">${memoryStatusPills(summary)}</div>
        <div class="insight-kpis">
          ${insightKpi('显示', memories.length, 'current filter')}
          ${insightKpi('活跃', summary.active || 0, 'active')}
          ${insightKpi('关注', summary.focused || 0, 'focused')}
          ${insightKpi('今日建议', suggested.length, 'clusters')}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>新建项目</h3><span class="muted">manual</span></div>
        <input id="memoryNewTitle" placeholder="项目名">
        <textarea id="memoryNewSummary" placeholder="这个项目的长期背景、目标、当前状态" style="margin-top:8px"></textarea>
        <input id="memoryNewKeywords" placeholder="关键词，用逗号分隔" style="margin-top:8px">
        <div class="overview-actions" style="margin-top:8px">
          <button class="btn primary" onclick="createProjectMemory()">创建记忆</button>
          <button class="btn" onclick="go('meeting')">开会</button>
        </div>
      </section>
    </div>
    <div class="insight-main">
      <section class="card">
        <div class="section-title"><h3>项目记忆</h3><span class="muted">${esc(memories.length)} shown</span></div>
        ${projectMemoryList(memories)}
      </section>
      <aside class="insight-side">
        <section class="card">
          <div class="section-title"><h3>今日可沉淀项目</h3><span class="muted">${esc(suggested.length)} clusters</span></div>
          ${suggestedProjectList(suggested)}
        </section>
      </aside>
    </div>`;
}
function projectMemoryList(rows){
  if(!(rows || []).length) return '<div class="empty-state">还没有项目记忆；可以从今日项目聚类或会议结束时写入。</div>';
  return `<div class="memory-list">${rows.map(projectMemoryCard).join('')}</div>`;
}
function projectMemoryCard(item){
  return `<article class="memory-card ${esc(item.status || '')}">
    <div class="memory-head">
      <div>
        <div class="memory-title">${esc(item.title || '未命名项目')}</div>
        <div class="item-meta">${esc(item.status || 'active')} · ${esc(item.evidence_count || 0)} evidence · latest ${esc(shortDateTime(item.last_seen_at || item.updated_at || ''))}</div>
      </div>
      ${status(item.status || 'active')}
    </div>
    <div class="memory-body">${esc(item.summary || '')}</div>
    <div class="project-keywords">${(item.keywords || []).slice(0,8).map(keyword => `<span class="evidence-chip">${esc(keyword)}</span>`).join('')}</div>
    ${memoryActionChips(item.next_actions || [])}
    ${memoryEventList(item.events || [])}
    <div class="memory-actions">
      <button class="btn primary" onclick="setMeetingProject('${escAttr(item.id)}','${escAttr(item.title || '')}')">开会</button>
      <button class="btn" onclick="projectMemoryAction({action:'update',project_id:'${escAttr(item.id)}',status:'focused'})">关注</button>
      <button class="btn" onclick="projectMemoryAction({action:'update',project_id:'${escAttr(item.id)}',status:'active'})">活跃</button>
      <button class="btn" data-query="${escAttr(item.title || item.summary || '')}" onclick="openInsightSearch(this)">问证据</button>
      <button class="btn danger" onclick="projectMemoryAction({action:'update',project_id:'${escAttr(item.id)}',status:'archived'})">归档</button>
    </div>
  </article>`;
}
function memoryActionChips(rows){
  if(!(rows || []).length) return '';
  return `<div class="project-keywords">${rows.slice(0,5).map(item => `<span class="evidence-chip">${esc(item.title || item.body || 'action')}</span>`).join('')}</div>`;
}
function memoryEventList(rows){
  if(!(rows || []).length) return '';
  return `<details class="insight-evidence"><summary>${esc(rows.length)} 最近事件</summary><div class="insight-evidence-list">${rows.slice(0,6).map(row => `<div class="insight-evidence-row"><b>${esc(row.title || row.source_ref)}</b><div class="muted">${esc(shortDateTime(row.observed_at || row.created_at || ''))}</div><div>${esc(row.summary || '')}</div></div>`).join('')}</div></details>`;
}
function suggestedProjectList(rows){
  if(!(rows || []).length) return '<div class="empty-state">今天还没有明显项目聚类</div>';
  return `<div class="meeting-list">${rows.slice(0,8).map(suggestedProjectCard).join('')}</div>`;
}
function suggestedProjectCard(item){
  return `<article class="meeting-card">
    <div class="meeting-head">
      <div><div class="meeting-title">${esc(item.title || '未命名项目')}</div><div class="item-meta">${esc(item.event_count || 0)} events · ${esc(Math.round(Number(item.confidence || 0) * 100))}%</div></div>
    </div>
    <div class="meeting-body">${esc(item.summary || '')}</div>
    <div class="project-keywords">${(item.keywords || []).map(keyword => `<span class="evidence-chip">${esc(keyword)}</span>`).join('')}</div>
    <div class="meeting-actions">
      <button class="btn primary" data-project="${escAttr(JSON.stringify(item))}" onclick="saveSuggestedProject(this)">写入项目记忆</button>
      <button class="btn" data-query="${escAttr(item.title || item.summary || '')}" onclick="openInsightSearch(this)">问证据</button>
    </div>
  </article>`;
}
function memoryStatusOptions(current){
  return [['active','活跃'], ['focused','关注'], ['paused','暂停'], ['archived','归档'], ['all','全部']].map(([value,label]) => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(label)}</option>`).join('');
}
function memoryStatusPills(summary){
  const rows = [['active','活跃', summary.active || 0], ['focused','关注', summary.focused || 0], ['archived','归档', summary.archived || 0], ['all','全部', summary.total || 0]];
  return rows.map(([key,label,count]) => `<button class="filter-pill ${state.memoryStatus===key?'active':''}" onclick="setMemoryStatus('${key}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function applyMemoryFilters(){
  state.memoryDate = $('memoryDate').value || 'today';
  state.memoryQ = $('memoryQ').value;
  state.memoryStatus = $('memoryStatus').value || 'active';
  projectMemory();
}
function memoryKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyMemoryFilters();
  }
}
function setMemoryDate(value){ state.memoryDate = value || 'today'; projectMemory(); }
function setMemoryStatus(value){ state.memoryStatus = value || 'active'; projectMemory(); }
async function createProjectMemory(){
  const payload = {
    action: 'create',
    title: $('memoryNewTitle').value,
    summary: $('memoryNewSummary').value,
    keywords: $('memoryNewKeywords').value,
  };
  const j = await api('/api/project-memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  toast(j.ok ? '已创建项目记忆' : '创建失败');
  projectMemory();
}
async function saveSuggestedProject(button){
  const project = JSON.parse(button.dataset.project || '{}');
  const j = await api('/api/project-memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'save_project',date:state.memoryDate || 'today',project})});
  toast(j.ok ? '已写入项目记忆' : '写入失败');
  projectMemory();
}
async function projectMemoryAction(payload){
  const j = await api('/api/project-memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  toast(j.ok ? '项目记忆已更新' : '更新失败');
  render();
}
async function personalMemory(){
  const buttons = `<button class="btn" onclick="setPersonalStatus('candidate')">记忆收件箱</button><button class="btn" onclick="setPersonalStatus('confirmed')">确认记忆</button><button class="btn" onclick="generatePersonalCandidates()">生成候选</button><button class="btn primary" onclick="personalMemory()">刷新</button>`;
  setHeader('个人档案','读取中...', buttons);
  const params = new URLSearchParams({date: state.personalDate || 'today', status: state.personalStatus || 'confirmed', type: state.personalType || 'all'});
  if(state.personalQ) params.set('q', state.personalQ);
  const j = await api('/api/personal-memory?' + params.toString());
  const summary = j.summary || {};
  const memories = j.memories || [];
  const suggested = j.suggested_candidates || [];
  const people = j.people || [];
  const conflicts = j.conflicts || [];
  const privacy = j.privacy || {};
  window.__personalPayload = j;
  $('subtitle').textContent = `${summary.profile_entries || 0} profile · ${summary.people || 0} people · ${summary.confirmed || 0} confirmed · ${summary.candidate || 0} candidate · ${summary.open_conflicts || 0} conflicts`;
  $('view').innerHTML = `
    <div class="insight-hero">
      <section class="card">
        <div class="section-title"><h3>个人档案</h3><span class="muted">${esc(shortDateTime(j.generated_at || ''))}</span></div>
        <div class="insight-toolbar projects">
          <input id="personalDate" value="${escAttr(state.personalDate || 'today')}" aria-label="date">
          <input id="personalQ" value="${escAttr(state.personalQ || '')}" placeholder="搜索个人事实、偏好、人物、证据" onkeydown="personalKey(event)" aria-label="search">
          <select id="personalType">${personalTypeOptions(state.personalType)}</select>
          <select id="personalStatus">${personalStatusOptions(state.personalStatus)}</select>
          <button class="btn primary" onclick="applyPersonalFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">${personalStatusPills(summary)}</div>
        <div class="insight-kpis">
          ${insightKpi('确认记忆', summary.confirmed || 0, 'answer/report context')}
          ${insightKpi('候选', summary.candidate || 0, 'needs review')}
          ${insightKpi('联系人', summary.people || 0, 'people files')}
          ${insightKpi('冲突', summary.open_conflicts || 0, 'needs decision')}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>快速写入</h3><span class="muted">manual</span></div>
        ${personalQuickCreateForm()}
      </section>
    </div>
    <div class="insight-main">
      <section class="card">
        <div class="section-title"><h3>${state.personalStatus === 'candidate' ? '记忆收件箱' : '确认记忆'}</h3><span class="muted">${esc(memories.length)} shown</span></div>
        ${personalMemoryList(memories)}
      </section>
      <aside class="insight-side">
        <section class="card">
          <div class="section-title"><h3>档案字段</h3><span class="muted">${esc(summary.profile_entries || 0)} entries</span></div>
          ${profileEditor()}
          ${profileSectionList((j.profile || {}).sections || [])}
        </section>
        <section class="card">
          <div class="section-title"><h3>候选提取</h3><span class="muted">${esc((summary.suggested || 0))} new</span></div>
          ${suggestedPersonalList(suggested)}
        </section>
        <section class="card">
          <div class="section-title"><h3>联系人档案</h3><span class="muted">${esc(people.length)} people</span></div>
          ${personEditor()}
          ${peopleList(people)}
        </section>
        <section class="card">
          <div class="section-title"><h3>冲突队列</h3><span class="muted">${esc(conflicts.length)} open</span></div>
          ${conflictList(conflicts)}
        </section>
        <section class="card">
          <div class="section-title"><h3>隐私与删除</h3><span class="muted">local only</span></div>
          ${personalPrivacyPanel(privacy)}
        </section>
      </aside>
    </div>`;
}
function personalQuickCreateForm(){
  return `<div class="settings-edit-list">
    <label class="settings-edit-row"><div class="settings-edit-label"><b>记忆类型</b><span>事实、偏好、决定、承诺、关系、节律或边界</span></div><div class="settings-edit-control"><select id="personalNewType">${personalTypeOptions('fact', false)}</select></div></label>
    <label class="settings-edit-row"><div class="settings-edit-label"><b>标题</b><span>短标题会进入问答证据</span></div><div class="settings-edit-control"><input id="personalNewTitle" placeholder="例如：报告默认要用中文"></div></label>
    <label class="settings-edit-row"><div class="settings-edit-label"><b>主体</b><span>人物、主题或偏好对象</span></div><div class="settings-edit-control"><input id="personalNewSubject" placeholder="例如：报告格式"></div></label>
    <label class="settings-edit-row"><div class="settings-edit-label"><b>内容</b><span>确认后的记忆会进入问答和报告上下文</span></div><div class="settings-edit-control"><textarea id="personalNewBody" placeholder="具体要记住什么"></textarea></div></label>
    <div class="overview-actions"><button class="btn primary" onclick="createPersonalMemory()">写入长期记忆</button></div>
  </div>`;
}
function profileEditor(){
  return `<details class="compact-details" open><summary>编辑档案字段</summary><div class="compact-details-body">
    <select id="profileSection">${profileSectionOptions()}</select>
    <input id="profileLabel" placeholder="字段名，例如 默认语言" style="margin-top:8px">
    <textarea id="profileValue" placeholder="字段值" style="margin-top:8px"></textarea>
    <select id="profileSensitivity" style="margin-top:8px">${sensitivityOptions('normal')}</select>
    <div class="overview-actions" style="margin-top:8px"><button class="btn primary" onclick="saveProfileEntry()">保存档案字段</button></div>
  </div></details>`;
}
function profileSectionList(sections){
  const nonEmpty = (sections || []).filter(section => (section.entries || []).length);
  if(!nonEmpty.length) return '<div class="empty-state">还没有个人档案字段。</div>';
  return `<div class="memory-list" style="margin-top:10px">${nonEmpty.map(section => `<article class="memory-card">
    <div class="memory-head"><div><div class="memory-title">${esc(section.label || section.id)}</div><div class="item-meta">${esc((section.entries || []).length)} entries</div></div></div>
    ${(section.entries || []).map(entry => `<div class="insight-state-row"><span><b>${esc(entry.label)}</b><br><span class="muted">${esc(entry.value)}</span></span><button class="btn danger" onclick="deleteProfileEntry('${escAttr(entry.id)}')">删除</button></div>`).join('')}
  </article>`).join('')}</div>`;
}
function personEditor(){
  return `<details class="compact-details"><summary>新增联系人</summary><div class="compact-details-body">
    <input id="personName" placeholder="姓名或显示名">
    <input id="personRelationship" placeholder="关系，例如 同事/学生/家人" style="margin-top:8px">
    <input id="personOrg" placeholder="组织" style="margin-top:8px">
    <textarea id="personNotes" placeholder="长期背景、沟通偏好、注意事项" style="margin-top:8px"></textarea>
    <div class="overview-actions" style="margin-top:8px"><button class="btn primary" onclick="createPerson()">创建联系人</button></div>
  </div></details>`;
}
function personalMemoryList(rows){
  if(!(rows || []).length) return '<div class="empty-state">当前筛选没有个人记忆。</div>';
  return `<div class="memory-list">${rows.map(personalMemoryCard).join('')}</div>`;
}
function personalMemoryCard(item){
  const conflict = Number(item.open_conflicts || 0) > 0 ? `<span class="status warn">${esc(item.open_conflicts)} conflict</span>` : '';
  return `<article class="memory-card ${esc(item.status || '')}">
    <div class="memory-head">
      <div>
        <div class="memory-title">${esc(item.title || '未命名记忆')}</div>
        <div class="item-meta">${esc(item.memory_type || 'note')} · ${esc(item.status || 'confirmed')} · ${esc(item.sensitivity || 'normal')} · ${esc(shortDateTime(item.updated_at || ''))}</div>
      </div>
      <div>${conflict}${status(item.status || 'confirmed')}</div>
    </div>
    <div class="memory-body">${esc(item.body || '')}</div>
    <div class="project-keywords">${[item.subject, item.person_name].filter(Boolean).map(value => `<span class="evidence-chip">${esc(value)}</span>`).join('')}</div>
    ${personalEvidenceList(item.evidence || [])}
    <div class="memory-actions">
      ${item.status !== 'confirmed' ? `<button class="btn primary" onclick="personalMemoryAction({action:'confirm_memory',memory_id:'${escAttr(item.id)}'})">确认</button>` : ''}
      <button class="btn" data-query="${escAttr(item.title || item.body || '')}" onclick="openInsightSearch(this)">问证据</button>
      ${item.status !== 'ignored' ? `<button class="btn" onclick="personalMemoryAction({action:'ignore_memory',memory_id:'${escAttr(item.id)}'})">忽略</button>` : ''}
      <button class="btn" onclick="personalMemoryAction({action:'archive_memory',memory_id:'${escAttr(item.id)}'})">归档</button>
      <button class="btn danger" onclick="deletePersonalMemory('${escAttr(item.id)}')">彻底删除</button>
    </div>
  </article>`;
}
function personalEvidenceList(rows){
  if(!(rows || []).length) return '';
  return `<details class="insight-evidence"><summary>${esc(rows.length)} evidence</summary><div class="insight-evidence-list">${rows.map(row => `<div class="insight-evidence-row"><b>${esc(row.title || row.source_ref)}</b><div class="muted">${esc(row.source_type || '')} · ${esc(shortDateTime(row.observed_at || ''))}</div><div>${esc(row.snippet || '')}</div></div>`).join('')}</div></details>`;
}
function suggestedPersonalList(rows){
  if(!(rows || []).length) return '<div class="empty-state">今天暂时没有新的候选记忆。</div>';
  return `<div class="memory-list">${rows.slice(0,8).map(candidate => `<article class="meeting-card ${candidate.already_saved?'ended':''}">
    <div class="meeting-head"><div><div class="meeting-title">${esc(candidate.title || '候选记忆')}</div><div class="item-meta">${esc(candidate.memory_type || 'note')} · ${esc(candidate.sensitivity || 'normal')} · ${candidate.already_saved ? 'saved ' + esc(candidate.existing_status || '') : 'new'}</div></div></div>
    <div class="meeting-body">${esc(candidate.body || '')}</div>
    <div class="meeting-actions">
      ${candidate.already_saved ? '' : `<button class="btn primary" data-candidate="${escAttr(JSON.stringify(candidate))}" onclick="saveSuggestedPersonal(this)">存入收件箱</button>`}
      <button class="btn" data-query="${escAttr(candidate.body || candidate.title || '')}" onclick="openInsightSearch(this)">问证据</button>
    </div>
  </article>`).join('')}</div>`;
}
function peopleList(rows){
  if(!(rows || []).length) return '<div class="empty-state">还没有联系人档案。</div>';
  return `<div class="memory-list" style="margin-top:10px">${rows.slice(0,12).map(person => {
    const sid = domId(person.id);
    return `<article class="meeting-card">
      <div class="meeting-head"><div><div class="meeting-title">${esc(person.display_name)}</div><div class="item-meta">${esc(person.relationship || 'person')} · ${esc(person.organization || '')} · ${esc(person.confirmed_memory_count || 0)} memories</div></div>${status(person.status || 'active')}</div>
      <div class="meeting-body">${esc(person.notes || '')}</div>
      <div class="project-keywords">${(person.aliases || []).map(alias => `<span class="evidence-chip">${esc(alias.alias)}</span>`).join('')}${(person.speaker_links || []).map(link => `<span class="evidence-chip">Voice ${esc(link.speaker_id)} ${esc(link.speaker_name || '')}</span>`).join('')}</div>
      <div class="speaker-tool-row" style="margin-top:8px"><input id="alias_${sid}" placeholder="新增别名"><button class="btn" onclick="addPersonAlias('${escAttr(person.id)}')">加别名</button></div>
      <div class="speaker-tool-row" style="margin-top:8px"><input id="speaker_${sid}" placeholder="说话人 ID"><button class="btn" onclick="linkPersonSpeaker('${escAttr(person.id)}')">链接 Voice</button></div>
    </article>`;
  }).join('')}</div>`;
}
function conflictList(rows){
  const open = (rows || []).filter(row => row.status === 'open');
  if(!open.length) return '<div class="empty-state">没有未解决冲突。</div>';
  return `<div class="memory-list">${open.slice(0,8).map(row => `<article class="meeting-card">
    <div class="meeting-head"><div><div class="meeting-title">${esc(row.reason || '记忆冲突')}</div><div class="item-meta">${esc(shortDateTime(row.created_at || ''))}</div></div>${status(row.status)}</div>
    <div class="meeting-body"><b>A:</b> ${esc(((row.memory || {}).title || ''))}<br><b>B:</b> ${esc(((row.conflicting_memory || {}).title || ''))}</div>
    <div class="meeting-actions"><button class="btn primary" onclick="resolvePersonalConflict('${escAttr(row.id)}')">标记已处理</button></div>
  </article>`).join('')}</div>`;
}
function personalPrivacyPanel(privacy){
  const sens = privacy.by_sensitivity || {};
  const sources = privacy.by_source || [];
  return `<div class="insight-state-list">
    ${Object.entries({normal:sens.normal||0, private:sens.private||0, high:sens.high||0}).map(([key,value]) => `<div class="insight-state-row"><span>${esc(key)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}
    <div class="privacy-note">个人记忆支持逐条彻底删除；删除会同时移除证据链接和 personal_memory 搜索索引。</div>
    ${sources.slice(0,5).map(row => `<div class="insight-state-row"><span>${esc(row.source)}</span><span class="queue-value">${esc(row.count)}</span></div>`).join('')}
  </div>`;
}
function personalTypeOptions(current, includeAll=true){
  const rows = [['all','全部'], ['fact','事实'], ['preference','偏好'], ['decision','决定'], ['commitment','承诺'], ['relationship','关系'], ['rhythm','节律'], ['boundary','边界'], ['project','项目'], ['note','备注']];
  return rows.filter(([value]) => includeAll || value !== 'all').map(([value,label]) => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(label)}</option>`).join('');
}
function personalStatusOptions(current){
  return [['candidate','候选'], ['confirmed','确认'], ['ignored','忽略'], ['archived','归档'], ['all','全部']].map(([value,label]) => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(label)}</option>`).join('');
}
function personalStatusPills(summary){
  const rows = [['candidate','候选', summary.candidate || 0], ['confirmed','确认', summary.confirmed || 0], ['archived','归档', summary.archived || 0], ['all','全部', (summary.candidate || 0) + (summary.confirmed || 0) + (summary.archived || 0)]];
  return rows.map(([key,label,count]) => `<button class="filter-pill ${state.personalStatus===key?'active':''}" onclick="setPersonalStatus('${key}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function profileSectionOptions(){
  return [['identity','身份'], ['work','工作/学习'], ['preferences','偏好'], ['boundaries','边界'], ['rhythm','节律'], ['focus','当前重点']].map(([value,label]) => `<option value="${escAttr(value)}">${esc(label)}</option>`).join('');
}
function sensitivityOptions(current){
  return [['normal','普通'], ['private','私人'], ['high','高敏']].map(([value,label]) => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(label)}</option>`).join('');
}
function applyPersonalFilters(){
  state.personalDate = $('personalDate').value || 'today';
  state.personalQ = $('personalQ').value;
  state.personalType = $('personalType').value || 'all';
  state.personalStatus = $('personalStatus').value || 'confirmed';
  personalMemory();
}
function personalKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyPersonalFilters();
  }
}
function setPersonalStatus(value){ state.personalStatus = value || 'confirmed'; personalMemory(); }
async function personalMemoryPost(payload, message){
  const j = await api('/api/personal-memory',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  toast(j.ok ? message : '操作失败');
  personalMemory();
}
async function personalMemoryAction(payload){ return personalMemoryPost(payload, '个人记忆已更新'); }
async function createPersonalMemory(){
  return personalMemoryPost({
    action:'create_memory',
    status:'confirmed',
    memory_type:$('personalNewType').value,
    title:$('personalNewTitle').value,
    subject:$('personalNewSubject').value,
    body:$('personalNewBody').value,
    source:'manual',
  }, '已写入长期记忆');
}
async function saveSuggestedPersonal(button){
  const candidate = JSON.parse(button.dataset.candidate || '{}');
  candidate.action = 'create_memory';
  candidate.status = 'candidate';
  return personalMemoryPost(candidate, '已存入记忆收件箱');
}
async function generatePersonalCandidates(){
  return personalMemoryPost({action:'generate_candidates',date:state.personalDate || 'today'}, '候选记忆已生成');
}
async function saveProfileEntry(){
  return personalMemoryPost({
    action:'upsert_profile',
    section:$('profileSection').value,
    label:$('profileLabel').value,
    value:$('profileValue').value,
    sensitivity:$('profileSensitivity').value,
  }, '档案字段已保存');
}
async function deleteProfileEntry(id){
  if(askConfirm('删除这个档案字段？')) return personalMemoryPost({action:'delete_profile',id}, '档案字段已删除');
}
async function createPerson(){
  return personalMemoryPost({
    action:'create_person',
    display_name:$('personName').value,
    relationship:$('personRelationship').value,
    organization:$('personOrg').value,
    notes:$('personNotes').value,
  }, '联系人已创建');
}
async function addPersonAlias(personId){
  const value = $(`alias_${domId(personId)}`).value;
  return personalMemoryPost({action:'add_alias',person_id:personId,alias:value}, '别名已保存');
}
async function linkPersonSpeaker(personId){
  const value = $(`speaker_${domId(personId)}`).value;
  return personalMemoryPost({action:'link_speaker',person_id:personId,speaker_id:value,status:'confirmed'}, '说话人已链接');
}
async function deletePersonalMemory(memoryId){
  if(askConfirm('彻底删除这条个人记忆及其证据链接？')) return personalMemoryPost({action:'delete_memory',memory_id:memoryId}, '个人记忆已彻底删除');
}
async function resolvePersonalConflict(conflictId){
  return personalMemoryPost({action:'resolve_conflict',conflict_id:conflictId,resolution:'handled_in_dashboard'}, '冲突已标记处理');
}
async function meetingMode(){
  const buttons = `<button class="btn" onclick="go('memory')">项目记忆</button><button class="btn" onclick="go('inbox')">处理队列</button><button class="btn primary" onclick="meetingMode()">刷新</button>`;
  setHeader('会议','读取中...', buttons);
  const j = await api('/api/meeting-mode');
  const active = j.active_meeting;
  const projects = j.projects || [];
  const recent = j.recent_meetings || [];
  $('subtitle').textContent = `${active ? '会议进行中' : '没有进行中的会议'} · ${projects.length} active projects · ${recent.length} recent`;
  $('view').innerHTML = `
    <div class="insight-hero">
      <section class="card meeting-active">
        ${active ? activeMeetingPanel(active) : startMeetingPanel(projects)}
      </section>
      <section class="card">
        <div class="section-title"><h3>会议项目</h3><span class="muted">${esc(projects.length)} projects</span></div>
        ${meetingProjectPicker(projects)}
      </section>
    </div>
    <div class="insight-main">
      <section class="card">
        <div class="section-title"><h3>最近会议</h3><span class="muted">${esc(recent.length)} sessions</span></div>
        ${meetingList(recent)}
      </section>
      <aside class="insight-side">
        <section class="card">
          <div class="section-title"><h3>会议流转</h3><span class="muted">local memory</span></div>
          <div class="overview-actions">
            <button class="btn" onclick="go('today')">今天时间线</button>
            <button class="btn" onclick="go('memory')">项目记忆</button>
            <button class="btn" onclick="go('inbox')">处理队列</button>
            <button class="btn" onclick="go('search')">证据问答</button>
          </div>
        </section>
      </aside>
    </div>`;
}
function startMeetingPanel(projects){
  return `<div>
    <div class="section-title"><h3>开始会议</h3><span class="muted">capture</span></div>
    <input id="meetingTitle" value="${escAttr(state.meetingTitle || '')}" placeholder="会议标题">
    <select id="meetingProject" style="margin-top:8px">${meetingProjectOptions(projects, state.meetingProjectId)}</select>
    <input id="meetingParticipants" placeholder="参与者，用逗号分隔" style="margin-top:8px">
    <textarea id="meetingAgenda" placeholder="议程 / 想确认的问题" style="margin-top:8px"></textarea>
    <div class="meeting-actions"><button class="btn primary" onclick="startMeeting()">开始会议记录</button></div>
  </div>`;
}
function activeMeetingPanel(active){
  return `<div>
    <div class="section-title"><h3>${esc(active.title || '会议')}</h3>${status(active.status || 'active')}</div>
    <div class="item-meta">${esc(shortDateTime(active.started_at || ''))} · ${esc((active.project || {}).title || '未关联项目')}</div>
    ${active.agenda ? `<div class="meeting-body">${esc(active.agenda)}</div>` : ''}
    <textarea id="meetingNote" placeholder="记录结论、分歧、行动项。包含“需要/确认/回复/截止”等词会进入处理队列。" style="margin-top:10px"></textarea>
    <div class="meeting-actions">
      <button class="btn primary" onclick="addMeetingNote('${escAttr(active.id)}')">记录笔记</button>
      <button class="btn danger" onclick="endMeeting('${escAttr(active.id)}')">结束并写入项目记忆</button>
    </div>
    ${meetingActionList(active.action_items || [])}
    ${meetingNotes(active.notes || '')}
  </div>`;
}
function meetingProjectPicker(projects){
  if(!(projects || []).length) return '<div class="empty-state">还没有活跃项目；可以先去项目记忆创建，或直接开始无项目会议。</div>';
  return `<div class="meeting-list">${projects.slice(0,8).map(project => `<div class="meeting-card"><div class="meeting-head"><div><div class="meeting-title">${esc(project.title)}</div><div class="item-meta">${esc(project.status)} · ${esc(project.evidence_count || 0)} evidence</div></div>${status(project.status)}</div><div class="meeting-actions"><button class="btn" onclick="setMeetingProject('${escAttr(project.id)}','${escAttr(project.title)}')">用于新会议</button></div></div>`).join('')}</div>`;
}
function meetingProjectOptions(projects, selected){
  const rows = [['','不关联项目'], ...(projects || []).map(project => [project.id, project.title])];
  return rows.map(([id,title]) => `<option value="${escAttr(id)}" ${selected===id?'selected':''}>${esc(title)}</option>`).join('');
}
function setMeetingProject(projectId, title){
  state.meetingProjectId = projectId || '';
  state.meetingTitle = title ? `${title} meeting` : state.meetingTitle;
  go('meeting');
}
async function startMeeting(){
  const payload = {
    action: 'start',
    title: $('meetingTitle').value,
    project_id: $('meetingProject').value,
    participants: $('meetingParticipants').value,
    agenda: $('meetingAgenda').value,
  };
  const j = await api('/api/meeting-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  toast(j.ok ? '会议记录已开始' : '开始失败');
  state.meetingTitle = '';
  meetingMode();
}
async function addMeetingNote(meetingId){
  const note = $('meetingNote').value.trim();
  if(!note) return toast('会议笔记为空');
  const j = await api('/api/meeting-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'note',meeting_id:meetingId,note})});
  toast(j.ok ? '已记录会议笔记' : '记录失败');
  meetingMode();
}
async function endMeeting(meetingId){
  const note = $('meetingNote') ? $('meetingNote').value.trim() : '';
  const j = await api('/api/meeting-mode',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action:'end',meeting_id:meetingId,note})});
  toast(j.ok ? '会议已结束并写入本地记忆' : '结束失败');
  meetingMode();
}
function meetingList(rows){
  if(!(rows || []).length) return '<div class="empty-state">还没有会议记录</div>';
  return `<div class="meeting-list">${rows.map(meetingCard).join('')}</div>`;
}
function meetingCard(item){
  return `<article class="meeting-card ${esc(item.status || '')}">
    <div class="meeting-head">
      <div><div class="meeting-title">${esc(item.title || '会议')}</div><div class="item-meta">${esc(shortDateTime(item.started_at || ''))} · ${esc((item.project || {}).title || '无项目')}</div></div>
      ${status(item.status || 'ended')}
    </div>
    <div class="meeting-body">${esc(item.summary || item.agenda || compactPlain(item.notes || '', 260))}</div>
    ${meetingActionList(item.action_items || [])}
  </article>`;
}
function meetingActionList(rows){
  if(!(rows || []).length) return '';
  return `<div class="project-keywords">${rows.slice(0,6).map(item => `<span class="evidence-chip">${esc(item.title || item.body || 'action')}</span>`).join('')}</div>`;
}
function meetingNotes(raw){
  const lines = String(raw || '').split('\\n').filter(Boolean).slice(-8);
  if(!lines.length) return '';
  return `<details class="insight-evidence"><summary>${esc(lines.length)} notes</summary><div class="meeting-note-list">${lines.map(line => `<div class="insight-evidence-row">${esc(line)}</div>`).join('')}</div></details>`;
}
function compactPlain(value, limit){
  const text = String(value || '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? text.slice(0, Math.max(0, limit - 1)) + '…' : text;
}
async function projectsWorkbench(){
  const buttons = `<button class="btn" onclick="setProjectDate('today')">今天</button><button class="btn" onclick="setProjectDate('yesterday')">昨天</button><button class="btn" onclick="bulkInsightState('project','archived')">当前归档</button><button class="btn primary" onclick="projectsWorkbench()">刷新</button>`;
  setHeader('项目聚类','读取中...', buttons);
  const params = new URLSearchParams({date: state.projectDate || 'today', status: state.projectStatus || 'active'});
  if(state.projectQ) params.set('q', state.projectQ);
  if(state.projectSource && state.projectSource !== 'all') params.set('source', state.projectSource);
  const j = await api('/api/project-clusters?' + params.toString());
  const summary = j.summary || {};
  const stateSummary = summary.state || {};
  const rows = j.projects || [];
  window.__projectItems = rows;
  $('subtitle').textContent = `${j.date || ''} · ${rows.length}/${summary.all || rows.length} 个项目 · ${summary.events || 0} 条证据`;
  $('view').innerHTML = `
    <div class="insight-hero">
      <section class="card">
        <div class="section-title"><h3>项目 / 主题工作台</h3><span class="muted">${esc(shortDateTime(j.generated_at || ''))}</span></div>
        <div class="insight-toolbar projects">
          <input id="projectDate" value="${escAttr(state.projectDate || 'today')}" aria-label="date">
          <input id="projectQ" value="${escAttr(state.projectQ || '')}" placeholder="搜索项目、关键词、证据" onkeydown="projectKey(event)" aria-label="search">
          <select id="projectSource">${insightSourceOptions(state.projectSource)}</select>
          <select id="projectStatus">${insightStatusOptions(state.projectStatus)}</select>
          <button class="btn primary" onclick="applyProjectFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">${insightStatusPills('project', state.projectStatus, summary)}</div>
        <div class="insight-kpis">
          ${insightKpi('项目', rows.length, 'current filter')}
          ${insightKpi('证据', summary.events || 0, 'events')}
          ${insightKpi('未处理', stateSummary.open || 0, 'open')}
          ${insightKpi('置顶', stateSummary.pinned || summary.pinned || 0, 'pinned')}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>项目动作</h3><span class="muted">curate</span></div>
        <div class="overview-actions">
          <button class="btn" onclick="go('inbox')">处理队列</button>
          <button class="btn" onclick="go('timeline')">时间线</button>
          <button class="btn" onclick="bulkInsightState('project','snoozed')">当前稍后</button>
          <button class="btn danger" onclick="bulkInsightState('project','archived')">当前归档</button>
        </div>
        ${projectCategoryBreakdown(rows)}
      </section>
    </div>
    <div class="insight-main">
      <section class="card">
        <div class="section-title"><h3>项目列表</h3><span class="muted">${esc(rows.length)} shown</span></div>
        ${projectWorkbenchList(rows)}
      </section>
      <aside class="insight-side">
        <section class="card">
          <div class="section-title"><h3>来源构成</h3><span class="muted">${esc(state.projectSource || 'all')}</span></div>
          ${projectCategoryBreakdown(rows)}
        </section>
        <section class="card">
          <div class="section-title"><h3>状态</h3></div>
          ${insightStateBreakdown(summary)}
        </section>
      </aside>
    </div>`;
}
function projectWorkbenchList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有匹配的项目聚类</div>';
  return `<div class="insight-list">${rows.map(projectWorkbenchCard).join('')}</div>`;
}
function projectWorkbenchCard(item){
  const stateInfo = item.state || {};
  const currentStatus = stateInfo.status || 'open';
  const pinned = !!stateInfo.pinned;
  const confidence = Math.round(Number(item.confidence || 0) * 100);
  return `<article class="insight-card project ${esc(currentStatus)}">
    <div class="insight-head">
      <div>
        <div class="insight-title">${pinned ? '★ ' : ''}${esc(item.title || '未命名项目')}</div>
        <div class="item-meta">${esc(shortDateTime((item.time_span || {}).start || ''))} -> ${esc(shortDateTime((item.time_span || {}).end || ''))} · ${esc(item.event_count || 0)} 条证据</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end"><span class="status ok">${esc(confidence)}%</span>${status(currentStatus)}</div>
    </div>
    <div class="insight-body">${esc(item.summary || '')}</div>
    <div class="insight-chips">
      ${(item.keywords || []).map(keyword => `<span class="evidence-chip">${esc(keyword)}</span>`).join('')}
      ${Object.entries(item.categories || {}).map(([key, value]) => `<span class="evidence-chip">${esc(categoryLabel(key))} ${esc(value)}</span>`).join('')}
    </div>
    ${projectNextActions(item.next_actions || [])}
    <div class="insight-actions">
	      <button class="btn primary" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="toggleInsightPin(this,'project')">${pinned ? '取消关注' : '关注'}</button>
	      <button class="btn" data-project="${escAttr(JSON.stringify(item))}" onclick="saveSuggestedProject(this)">写入项目记忆</button>
	      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'project','done')">完成</button>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'project','snoozed')">稍后</button>
      <button class="btn" data-query="${escAttr(item.title || item.summary || '')}" onclick="openInsightSearch(this)">问项目证据</button>
      <button class="btn danger" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="setInsightState(this,'project','archived')">归档</button>
    </div>
    <div class="insight-note">
      <textarea data-insight-note placeholder="项目备注">${esc(stateInfo.note || '')}</textarea>
      <button class="btn" data-item-id="${escAttr(item.id)}" data-status="${escAttr(currentStatus)}" data-pinned="${escAttr(pinned)}" onclick="saveInsightNote(this,'project')">保存备注</button>
    </div>
    ${insightEvidenceDetails(item.evidence || [])}
  </article>`;
}
function projectNextActions(rows){
  if(!(rows || []).length) return '';
  return `<div class="insight-chips">${rows.map(item => `<span class="evidence-chip">${esc(item.title || item.kind || 'next')}</span>`).join('')}</div>`;
}
function insightEvidenceDetails(rows){
  if(!(rows || []).length) return '';
  return `<details class="insight-evidence"><summary>证据 ${esc(rows.length)}</summary><div class="insight-evidence-list">${rows.map(evidence => `<div class="insight-evidence-row">
    <b>${esc(evidence.title || evidence.id || 'evidence')}</b>
    <div class="item-meta">${esc(shortDateTime(evidence.time || ''))} · ${esc(evidence.source || '')}/${esc(evidence.kind || '')}${evidence.category ? ' · ' + esc(categoryLabel(evidence.category)) : ''}</div>
    <div class="result-text">${esc(evidence.snippet || evidence.body || evidence.location || '')}</div>
  </div>`).join('')}</div></details>`;
}
function insightKpi(label, value, hint){
  return `<div class="insight-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function insightStatusPills(itemType, current, summary){
  const stateSummary = (summary || {}).state || {};
  const total = Number((summary || {}).all || (summary || {}).total || (summary || {}).projects || 0);
  const rows = [
    ['active', '活跃', stateSummary.active ?? total],
    ['open', '未处理', stateSummary.open || 0],
    ['snoozed', '稍后', stateSummary.snoozed || 0],
    ['done', '已完成', stateSummary.done || 0],
    ['archived', '已归档', stateSummary.archived || 0],
    ['all', '全部', total],
  ];
  const fn = itemType === 'project' ? 'setProjectStatus' : 'setSuggestionStatus';
  return rows.map(([key, label, count]) => `<button class="filter-pill ${current===key?'active':''}" onclick="${fn}('${key}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function insightStatusOptions(current){
  return ['active','open','snoozed','done','archived','all'].map(value => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(insightStatusLabel(value))}</option>`).join('');
}
function insightStatusLabel(value){
  return ({active:'活跃',open:'未处理',snoozed:'稍后',done:'已完成',archived:'已归档',dismissed:'已忽略',all:'全部'})[value] || value || '活跃';
}
function insightStateBreakdown(summary){
  const states = (summary || {}).state || {};
  const rows = [['open','未处理'], ['snoozed','稍后'], ['done','已完成'], ['archived','已归档'], ['dismissed','已忽略'], ['pinned','置顶']];
  return `<div class="insight-state-list" style="margin-top:12px">${rows.map(([key,label]) => `<div class="insight-state-row"><span>${esc(label)}</span><span class="queue-value">${esc(states[key] || 0)}</span></div>`).join('')}</div>`;
}
function suggestionPriorityOptions(current){
  return ['all','high','medium','low'].map(value => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(priorityLabel(value))}</option>`).join('');
}
function suggestionPriorityPills(summary){
  const rows = [['all','全部', (summary || {}).total || 0], ['high','高', (summary || {}).high || 0], ['medium','中', ''], ['low','低', '']];
  return rows.map(([key,label,count]) => `<button class="filter-pill ${state.suggestionPriority===key?'active':''}" onclick="setSuggestionPriority('${key}')">${esc(label)}${count !== '' ? ` <span class="chip-count">${esc(count)}</span>` : ''}</button>`).join('');
}
function priorityLabel(value){
  return ({all:'全部优先级',high:'高优先级',medium:'中优先级',low:'低优先级'})[value] || value || '全部优先级';
}
function insightSourceOptions(current){
  const values = [['all','全部来源'], ['mobile','mobile'], ['feedback','feedback'], ['audio','录音'], ['calendar','日程'], ['reminder','提醒'], ['files','文件'], ['location','位置'], ['app','App'], ['system','系统']];
  return values.map(([value,label]) => `<option value="${escAttr(value)}" ${current===value?'selected':''}>${esc(label)}</option>`).join('');
}
function applySuggestionFilters(){
  state.suggestionDate = $('suggestionDate').value || 'today';
  state.suggestionQ = $('suggestionQ').value;
  state.suggestionPriority = $('suggestionPriority').value || 'all';
  state.suggestionSource = $('suggestionSource').value || 'all';
  suggestionInbox();
}
function suggestionKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applySuggestionFilters();
  }
}
function setSuggestionDate(value){ state.suggestionDate = value || 'today'; suggestionInbox(); }
function setSuggestionStatus(value){ state.suggestionStatus = value || 'active'; suggestionInbox(); }
function setSuggestionPriority(value){ state.suggestionPriority = value || 'all'; suggestionInbox(); }
function applyProjectFilters(){
  state.projectDate = $('projectDate').value || 'today';
  state.projectQ = $('projectQ').value;
  state.projectSource = $('projectSource').value || 'all';
  state.projectStatus = $('projectStatus').value || 'active';
  projectsWorkbench();
}
function projectKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyProjectFilters();
  }
}
function setProjectDate(value){ state.projectDate = value || 'today'; projectsWorkbench(); }
function setProjectStatus(value){ state.projectStatus = value || 'active'; projectsWorkbench(); }
async function setInsightState(button, itemType, statusValue, pinnedValue){
  const note = button.closest('.insight-card')?.querySelector('[data-insight-note]')?.value || '';
  const payload = {item_id: button.dataset.itemId, item_type: itemType, status: statusValue, note};
  if(pinnedValue !== undefined) payload.pinned = pinnedValue;
  const j = await api('/api/insight-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  toast(j.ok ? '已更新处理状态' : '状态更新失败');
  render();
}
function toggleInsightPin(button, itemType){
  const pinned = !(button.dataset.pinned === 'true');
  setInsightState(button, itemType, button.dataset.status || 'open', pinned);
}
function saveInsightNote(button, itemType){
  setInsightState(button, itemType, button.dataset.status || 'open', button.dataset.pinned === 'true');
}
async function bulkInsightState(itemType, statusValue){
  const items = itemType === 'project' ? (window.__projectItems || []) : (window.__suggestionItems || []);
  if(!items.length) return toast('当前列表为空');
  for(const item of items){
    await api('/api/insight-state',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({item_id:item.id,item_type:itemType,status:statusValue})});
  }
  toast(`已更新 ${items.length} 条`);
  render();
}
function openInsightSearch(button){
  const q = button.dataset.query || '';
  state.searchQ = q;
  state.searchQuestion = q ? `围绕这个事项给我证据和下一步：${q}` : state.searchQuestion;
  go('search');
}
function projectCategoryBreakdown(rows){
  const counts = {};
  (rows || []).forEach(project => {
    Object.entries(project.categories || {}).forEach(([key,value]) => { counts[key] = (counts[key] || 0) + Number(value || 0); });
  });
  const entries = Object.entries(counts).sort((a,b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  if(!entries.length) return '<div class="empty-state" style="margin-top:12px">当前筛选没有来源构成</div>';
  return `<div class="insight-breakdown" style="margin-top:12px">${entries.map(([key,value]) => `<div class="insight-state-row"><span>${esc(categoryLabel(key))}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
async function render(){
  if(state.section==='setup') return setup();
  if(state.section==='action') return actionCenter();
  if(state.section==='inbox') return actionInbox();
  if(state.section==='suggestions') return suggestionInbox();
  if(state.section==='projects') return projectsWorkbench();
  if(state.section==='memory') return projectMemory();
  if(state.section==='personal') return personalMemory();
  if(state.section==='meeting') return meetingMode();
  if(state.section==='today') return today();
  if(state.section==='overview') return overview();
  if(state.section==='doctor') return doctor();
  if(state.section==='audio') return audio();
  if(state.section==='search') return search();
  if(state.section==='timeline') return timeline();
  if(state.section==='reports') return reports();
  if(state.section==='sources') return sources();
  if(state.section==='speaker-training') return speakerTraining();
  if(state.section==='speakers') return speakers();
  if(state.section==='files') return files();
  if(state.section==='recycle') return recycle();
  if(state.section==='sync') return sync();
  if(state.section==='privacy') return privacyCenter();
  if(state.section==='maintenance') return maintenance();
  if(state.section==='settings') return settings();
}
async function setup(){
  setHeader('启动向导','读取中...',
    `<button class="btn primary" onclick="setup()">刷新状态</button>`);
  const j = await api('/api/setup');
  const summary = j.summary || {};
  const syncInfo = j.sync || {};
  const cfg = j.config || {};
  $('subtitle').textContent = `${summary.complete || 0}/${summary.total || 0} 完成 · ${summary.percent || 0}% · ${j.generated_at || ''}`;
  $('view').innerHTML = `
    <div class="setup-hero">
      <section class="card">
        <div class="section-title"><h3>首次配置进度</h3>${status(summary.ready ? 'ok' : 'warn')}</div>
        <div class="setup-kpis">
          ${setupKpi('完成度', `${summary.percent || 0}%`, `${summary.complete || 0}/${summary.total || 0} steps`)}
          ${setupKpi('Token', syncInfo.token_configured ? '已配置' : '未配置', 'iPhone sync')}
          ${setupKpi('Sync Port', syncInfo.port || '-', syncInfo.host || '-')}
          ${setupKpi('Records', ((cfg.counts || {}).observations || 0), 'observations')}
        </div>
        <div class="setup-progress"><span style="width:${Math.max(0, Math.min(100, Number(summary.percent || 0)))}%"></span></div>
      </section>
      <section class="card">
        <div class="section-title"><h3>快捷操作</h3><span class="muted">setup</span></div>
        <div class="setup-actions">
          <button class="btn primary" onclick="setupGenerateToken()">生成新 token</button>
          <button class="btn" onclick="setupInstallAll()">安装全部服务</button>
          <button class="btn" onclick="action('install_sync_agent',{load:true})">安装同步服务</button>
          <button class="btn" onclick="action('install_agent',{load:true})">安装采集 Agent</button>
          <button class="btn" onclick="action('install_dashboard_agent',{load:true})">安装 Dashboard</button>
        </div>
      </section>
    </div>
    <div class="setup-main">
      <div class="setup-stack">
        <section class="card">
          <div class="section-title"><h3>检查清单</h3><span class="muted">${esc(summary.complete || 0)} ready</span></div>
          ${setupStepList(j.steps || [])}
        </section>
        <section class="card">
          <div class="section-title"><h3>iPhone 连接</h3><span class="muted">Mac sync URL</span></div>
          ${setupUrlList(syncInfo.upload_urls || [])}
          ${setupTokenPanel(syncInfo)}
        </section>
      </div>
      <aside class="setup-side">
        <section class="card">
          <div class="section-title"><h3>Mac 服务</h3><span class="muted">LaunchAgent</span></div>
          ${setupServiceList(j.services || [])}
        </section>
        <section class="card">
          <div class="section-title"><h3>本机路径</h3><span class="muted">${esc(cfg.timezone || '')}</span></div>
          <div class="settings-row-list">
            <div class="settings-row"><div class="label">config</div><div class="value">${esc(cfg.path || '')}</div></div>
            <div class="settings-row"><div class="label">database</div><div class="value">${esc(cfg.database || '')}</div></div>
            <div class="settings-row"><div class="label">data</div><div class="value">${esc(cfg.data_dir || '')}</div></div>
            <div class="settings-row"><div class="label">health</div><div class="value">${esc(syncInfo.health_url || '')}</div></div>
          </div>
        </section>
      </aside>
    </div>`;
}
function setupKpi(label, value, hint){
  return `<div class="setup-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function setupStepList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有检查项</div>';
  return `<div class="setup-step-list">${rows.map(item => `<div class="setup-step">
    <div>${status(item.status || (item.ok ? 'ok' : 'warn'))}</div>
    <div><div class="setup-title">${esc(item.title || item.key)}</div><div class="setup-detail">${esc(item.detail || '')}</div></div>
    ${item.ok ? '<span class="muted">ready</span>' : '<span class="muted">todo</span>'}
  </div>`).join('')}</div>`;
}
function setupServiceList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有服务状态</div>';
  return `<div class="setup-service-list">${rows.map(row => `<div class="setup-service">
    <div>${status(row.status || 'warn')}</div>
    <div><div class="setup-title">${esc(row.title || row.key)}</div><div class="setup-detail">${esc(row.label || '')}<br>${esc(row.path || '')}<br>${esc(row.installed ? 'installed' : 'missing')}, ${esc(row.state || '')}</div></div>
    <button class="btn" onclick="action('${escAttr(row.action)}',{load:true})">安装</button>
  </div>`).join('')}</div>`;
}
function setupUrlList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有可用 URL；请确认同步端口配置。</div>';
  return `<div class="setup-url-list">${rows.map(row => `<div class="setup-url-row">
    <div class="muted">${esc(row.label || 'URL')}</div>
    <div class="setup-url">${esc(row.url || '')}</div>
    <button class="btn" data-copy="${escAttr(row.url || '')}" onclick="copyFromButton(this,'URL')">复制 URL</button>
  </div>`).join('')}</div>`;
}
function setupTokenPanel(syncInfo){
  const token = state.setupToken || '';
  return `<div class="setup-token-box" style="margin-top:12px">
    <div class="section-title"><h3>同步 Token</h3>${status(syncInfo.token_configured ? 'ok' : 'warn')}</div>
    ${token ? `<div class="setup-token-value">${esc(token)}</div><div class="setup-actions"><button class="btn primary" data-copy="${escAttr(token)}" onclick="copyFromButton(this,'token')">复制 token</button><button class="btn" onclick="state.setupToken=''; setup()">隐藏 token</button></div>` : `<div class="setup-detail">${syncInfo.token_configured ? '已有 token。为了安全，现有 token 不会明文显示；需要配置新手机时可以生成一个新的。' : '还没有 token。先生成 token，再把 URL 和 token 填到 iPhone 的 Wond 设置里。'}</div><button class="btn primary" onclick="setupGenerateToken()">生成新 token</button>`}
  </div>`;
}
async function setupGenerateToken(){
  const j = await api('/api/setup-token',{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
  state.setupToken = j.token || '';
  toast(state.setupToken ? '已生成并保存新 token' : 'token 生成失败');
  await setup();
}
async function setupInstallAll(){
  const actions = [
    ['install_sync_agent', {load:true}],
    ['install_agent', {load:true}],
    ['install_dashboard_agent', {load:true}],
  ];
  for(const [name, args] of actions){
    await action(name, args);
  }
  setup();
}
async function copyFromButton(button, label){
  await copyText(button.dataset.copy || '');
  toast(`已复制 ${label || ''}`);
}
async function copyText(text){
  if(!text) return;
  if(navigator.clipboard && navigator.clipboard.writeText){
    await navigator.clipboard.writeText(text);
    return;
  }
  const input = document.createElement('textarea');
  input.value = text;
  input.style.position = 'fixed';
  input.style.opacity = '0';
  document.body.appendChild(input);
  input.select();
  document.execCommand('copy');
  document.body.removeChild(input);
}
async function today(){
  setHeader('今天','读取中...',
    `<button class="btn" onclick="action('collect',{date:state.todayDate})">采集</button><button class="btn" onclick="action('analyze_audio',{limit:10})">分析 10 条</button><button class="btn" onclick="go('timeline')">底层时间线</button><button class="btn primary" onclick="today()">刷新</button>`);
  const params = new URLSearchParams({date: state.todayDate || 'today'});
  if(state.todayQ) params.set('q', state.todayQ);
  if(state.todayFrom) params.set('time_from', state.todayFrom);
  if(state.todayTo) params.set('time_to', state.todayTo);
  const j=await api('/api/today?'+params.toString());
  const counts = j.summary.by_category || {};
  const allEvents = j.events || [];
  const events = filterTodayEvents(allEvents);
  const shown = events.length;
  const total = Number(j.summary.total || allEvents.length || 0);
  $('subtitle').textContent = `${j.date} · ${shown}/${total} 条 · ${shortRange(j.summary.first, j.summary.last)}`;
  $('view').innerHTML = `
    <div class="card today-controls">
      <div class="day-toolbar">
        <input id="todayDate" value="${esc(state.todayDate)}" aria-label="date">
        <input id="todayFrom" value="${esc(state.todayFrom)}" placeholder="开始 HH:MM" aria-label="start time">
        <input id="todayTo" value="${esc(state.todayTo)}" placeholder="结束 HH:MM" aria-label="end time">
        <input id="todayQ" value="${esc(state.todayQ)}" placeholder="搜索时间、人物、应用、地点、摘要" aria-label="search">
        <button class="btn primary" onclick="applyTodaySearch()">查找</button>
      </div>
      <div class="quickbar">
        <button class="filter-pill ${state.todayDate==='today'?'active':''}" onclick="setTodayDate('today')">今天</button>
        <button class="filter-pill ${state.todayDate==='yesterday'?'active':''}" onclick="setTodayDate('yesterday')">昨天</button>
        <button class="filter-pill ${!state.todayFrom&&!state.todayTo?'active':''}" onclick="setTodayRange('','')">全天</button>
        <button class="filter-pill ${rangeActive('09:00','12:00')?'active':''}" onclick="setTodayRange('09:00','12:00')">上午</button>
        <button class="filter-pill ${rangeActive('12:00','18:00')?'active':''}" onclick="setTodayRange('12:00','18:00')">下午</button>
        <button class="filter-pill ${rangeActive('18:00','23:59')?'active':''}" onclick="setTodayRange('18:00','23:59')">晚上</button>
        <button class="filter-pill ${rangeActive('09:00','18:00')?'active':''}" onclick="setTodayRange('09:00','18:00')">工作时间</button>
      </div>
    </div>
    <div class="today-summary">
      <div class="card">
        <div class="section-title"><h3>日内概览</h3><span class="muted">${esc(shortRange(j.summary.first, j.summary.last))}</span></div>
        <div class="today-stats">
          ${todayStat('事件', total, `${shown} 条显示`)}
          ${todayStat('录音', counts.audio || 0, `${j.summary.pending_audio_today || 0} 待处理`)}
          ${todayStat('聊天', counts.chat || 0, 'metadata')}
          ${todayStat('文件/位置/提醒', `${counts.file||0}/${counts.location||0}/${counts.reminder||0}`, 'today')}
        </div>
        ${hourBars(allEvents)}
      </div>
      <div class="card">
        <div class="section-title"><h3>分类</h3><span class="muted">${esc(categoryLabel(state.todayCategory))}</span></div>
        ${categoryFilters(counts, total)}
      </div>
    </div>
    <div class="today-main">
      <div>
        <div class="section-title"><h3>事件流</h3><span class="muted">${esc(j.generated_at)}</span></div>
        <div class="day-feed">${eventSections(events)}</div>
      </div>
      <div class="today-sidebar">
        <div class="card">
          <div class="section-title"><h3>音频</h3>${status((j.summary.pending_audio_today||0) ? 'pending' : 'ok')}</div>
          <table><tbody>
            <tr><td>今天待处理</td><td>${esc(j.summary.pending_audio_today || 0)}</td></tr>
            <tr><td>全部 pending</td><td>${esc((j.summary.audio.statuses||{}).pending || 0)}</td></tr>
            <tr><td>已有摘要</td><td>${esc(j.summary.audio.with_summary || 0)}</td></tr>
            <tr><td>最近分析</td><td>${esc(j.summary.audio.latest_analyzed || '-')}</td></tr>
          </tbody></table>
        </div>
        <div class="card">
          <div class="section-title"><h3>每日反馈</h3></div>
          <select id="feedbackCategory">
            <option value="important">重要</option>
            <option value="unimportant">不重要</option>
            <option value="wrong">错了</option>
            <option value="correction">纠正</option>
          </select>
          <textarea id="feedbackNote" placeholder="写下哪些总结重要、不重要或需要修正" style="margin-top:8px"></textarea>
          <button class="btn primary" style="margin-top:8px" onclick="submitFeedback()">写入长期记忆</button>
          <div style="margin-top:12px">
            <div class="section-title"><h3>已记录</h3><span class="muted">${esc((j.feedback||[]).length)} 条</span></div>
            ${(j.feedback||[]).map(f=>`<div class="feedback-row"><b>${esc(feedbackLabel(f.category))}</b><div class="muted">${esc(f.created_at)} ${esc(f.source_ref||'')}</div><div>${esc(f.note)}</div></div>`).join('') || '<div class="muted">暂无反馈</div>'}
          </div>
        </div>
      </div>
    </div>`;
}
function applyTodaySearch(){
  state.todayDate = $('todayDate').value || 'today';
  state.todayFrom = $('todayFrom').value;
  state.todayTo = $('todayTo').value;
  state.todayQ = $('todayQ').value;
  state.todayCategory = 'all';
  today();
}
function setTodayDate(value){
  state.todayDate = value;
  state.todayCategory = 'all';
  today();
}
function setTodayRange(from, to){
  state.todayFrom = from;
  state.todayTo = to;
  today();
}
function setTodayCategory(value){
  state.todayCategory = value || 'all';
  today();
}
function rangeActive(from, to){ return state.todayFrom === from && state.todayTo === to; }
function filterTodayEvents(rows){
  if(!state.todayCategory || state.todayCategory === 'all') return rows || [];
  return (rows || []).filter(event => String(event.category || 'other') === state.todayCategory);
}
function todayStat(label, value, hint){
  return `<div class="today-stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint||'')}</div></div>`;
}
function categoryFilters(counts, total){
  const order = ['all','app','audio','chat','file','location','reminder','calendar','bookmark','mail','web','feedback','system','other'];
  const items = order.map(key => [key, key === 'all' ? total : Number(counts[key] || 0)]).filter(([key,count]) => key === 'all' || count > 0);
  return `<div class="category-strip">${items.map(([key,count]) => `<button class="filter-pill category-chip ${state.todayCategory===key?'active':''}" onclick="setTodayCategory('${key}')"><span>${esc(categoryLabel(key))}</span><span class="chip-count">${esc(count)}</span></button>`).join('')}</div>`;
}
function hourBars(rows){
  const buckets = Array.from({length: 24}, () => 0);
  (rows || []).forEach(event => {
    const minutes = minutesOfDay(event.time);
    if(minutes >= 0) buckets[Math.floor(minutes / 60)] += 1;
  });
  const max = Math.max(1, ...buckets);
  const bars = buckets.map((count, hour) => {
    const height = count ? Math.max(8, Math.round((count / max) * 48)) : 5;
    const opacity = count ? (0.28 + (count / max) * 0.62).toFixed(2) : 0.15;
    return `<div class="hour-bar" title="${String(hour).padStart(2,'0')}:00 · ${count}" style="height:${height}px;opacity:${opacity}"></div>`;
  }).join('');
  return `<div class="hour-bars">${bars}</div><div class="hour-axis"><span>00</span><span>06</span><span>12</span><span>18</span><span>24</span></div>`;
}
async function submitFeedback(){
  const note = $('feedbackNote').value.trim();
  if(!note) return toast('反馈内容为空');
  const payload = {date: state.todayDate || 'today', category: $('feedbackCategory').value, note};
  const j = await api('/api/daily-feedback',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});
  toast(j.ok ? '已写入每日反馈' : '写入失败');
  today();
}
async function overview(){
  setHeader('系统总览','读取中...',
    `<button class="btn primary" onclick="action('collect',{date:'today'})">采集并写报告</button><button class="btn" onclick="action('refresh_report',{date:'today'})">刷新今日报告</button><button class="btn" onclick="render()">刷新</button>`);
  const j=await api('/api/overview');
  const health = j.health || {};
  const healthInfo = overviewHealthInfo(health);
  const reports = j.reports || {};
  const audioStatuses = (j.audio || {}).statuses || {};
  const latest = j.latest_observation || j.latest_activity || '-';
  $('subtitle').textContent = `${j.today || 'today'} · ${healthInfo.ok}/${healthInfo.total} health · latest ${latest}`;
  $('view').innerHTML = `
    <div class="overview-hero">
      <div class="card">
        <div class="section-title"><h3>运行状态</h3>${status(healthInfo.status)}</div>
        <div class="overview-kpis">
          ${overviewKpi('Observations', j.counts.observations, `latest ${j.latest_observation || '-'}`)}
          ${overviewKpi('Activity', j.counts.activity_samples, `latest ${j.latest_activity || '-'}`)}
          ${overviewKpi('Audio', `${audioStatuses.ok||0}/${(j.audio||{}).total||0}`, `${audioStatuses.pending||0} pending`)}
          ${overviewKpi('Speakers', j.counts.speakers, `${j.counts.speaker_samples} samples`)}
        </div>
        <div class="overview-health">
          ${overviewHealthItems(health)}
        </div>
      </div>
      <div class="card">
        <div class="section-title"><h3>待处理</h3><span class="muted">${esc(j.today || '')}</span></div>
        <div class="overview-queue">
          <div class="queue-row"><span>今日录音待处理</span><span class="queue-value">${esc(j.pending_audio_today || 0)}</span></div>
          <div class="queue-row"><span>全部 audio pending</span><span class="queue-value">${esc(audioStatuses.pending || 0)}</span></div>
          <div class="queue-row"><span>报告文件</span><span class="queue-value">${esc(reports.reports || 0)}</span></div>
          <div class="queue-row"><span>最近日报</span><span class="queue-value">${esc(shortPath(reports.latest_report || '-'))}</span></div>
        </div>
      </div>
    </div>
    <div class="overview-main">
      <div class="grid">
        <div class="card">
          <div class="section-title"><h3>Recent Collector Runs</h3><span class="muted">${esc((j.recent_runs||[]).length)} runs</span></div>
          ${runsTable(j.recent_runs || [])}
        </div>
        <div class="card">
          <div class="section-title"><h3>Observation Sources</h3><span class="muted">top sources</span></div>
          ${sourceCountTable((j.source_counts || []).slice(0, 12))}
        </div>
      </div>
      <div class="overview-side">
        <div class="card">
          <div class="section-title"><h3>快捷入口</h3></div>
          <div class="overview-actions">
            <button class="btn" onclick="go('today')">今天</button>
            <button class="btn" onclick="go('audio')">音频队列</button>
            <button class="btn" onclick="go('reports')">报告</button>
            <button class="btn" onclick="go('sync')">手机同步</button>
          </div>
        </div>
        <div class="card">
          <div class="section-title"><h3>维护</h3></div>
          <div class="overview-actions">
            <button class="btn" onclick="action('retention',{date:'today'})">Retention dry-run</button>
            <button class="btn" onclick="action('email_due',{})">Email due dry-run</button>
            <button class="btn" onclick="action('compact',{date:'today',period:'all'})">Compact</button>
            <button class="btn" onclick="go('maintenance')">记录维护</button>
          </div>
        </div>
        <div class="card">
          <div class="section-title"><h3>Reports</h3></div>
          <table><tbody>${Object.entries(reports).map(([k,v])=>`<tr><td>${esc(k)}</td><td>${esc(k==='latest_report' ? shortPath(v) : v)}</td></tr>`).join('')}</tbody></table>
        </div>
      </div>
    </div>`;
}
function overviewKpi(label, value, hint){
  return `<div class="overview-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint||'')}</div></div>`;
}
function overviewHealthInfo(health){
  const values = Object.values(health || {});
  const total = values.length;
  const ok = values.filter(Boolean).length;
  return { ok, total, status: total && ok < total ? 'warn' : 'ok' };
}
function overviewHealthItems(health){
  return Object.entries(health || {}).map(([key,value]) => `<div class="health-item"><span>${esc(healthLabel(key))}</span>${status(value?'ok':'warn')}</div>`).join('') || '<div class="muted">No health checks</div>';
}
function healthLabel(key){
  return ({sync:'Sync server',ollama:'Ollama',agent_plist:'Collector agent',sync_plist:'Sync agent',dashboard_plist:'Dashboard agent'})[key] || key;
}
async function doctor(){
  setHeader('诊断','读取中...',
    `<button class="btn primary" onclick="doctor()">Run checks</button><button class="btn" onclick="go('sources')">来源</button>`);
  const j=await api('/api/doctor');
  const checks = j.checks || [];
  const summary = doctorSummary(checks);
  const filtered = filterDoctorChecks(checks);
  const issues = checks.filter(c => c.status === 'fail' || c.status === 'warn');
  $('subtitle').textContent = `${j.overall} · ${summary.fail} fail / ${summary.warn} warn / ${summary.ok} ok · ${j.generated_at}`;
  $('view').innerHTML = `
    <div class="doctor-hero">
      <div class="card">
        <div class="section-title"><h3>诊断状态</h3>${status(j.overall)}</div>
        <div class="doctor-kpis">
          ${doctorKpi('Fail', summary.fail, 'needs action')}
          ${doctorKpi('Warn', summary.warn, 'degraded')}
          ${doctorKpi('OK', summary.ok, 'healthy')}
          ${doctorKpi('Areas', summary.areas, `${summary.total} checks`)}
        </div>
        <div class="doctor-filters">${doctorStatusFilters(summary)}</div>
      </div>
      <div class="card">
        <div class="section-title"><h3>修复入口</h3><span class="muted">LaunchAgents</span></div>
        <div class="overview-actions">
          <button class="btn" onclick="action('install_agent',{load:true})">Install Agent</button>
          <button class="btn" onclick="action('install_sync_agent',{load:true})">Install Sync Agent</button>
          <button class="btn" onclick="action('install_dashboard_agent',{load:true})">Install Dashboard</button>
          <button class="btn" onclick="go('sources')">来源状态</button>
        </div>
      </div>
    </div>
    <div class="doctor-main">
      <div class="grid">
        <div class="card">
          <div class="section-title"><h3>优先处理</h3><span class="muted">${esc(issues.length)} issues</span></div>
          ${doctorIssueList(issues)}
        </div>
        <div class="card">
          <div class="section-title"><h3>检查明细</h3><span class="muted">${esc(filtered.length)}/${esc(checks.length)} checks</span></div>
          ${doctorCheckList(filtered)}
        </div>
      </div>
      <div class="doctor-side">
        <details class="card compact-details">
          <summary>Area · ${esc(state.doctorArea)}</summary>
          <div class="compact-details-body">${doctorAreaList(checks)}</div>
        </details>
        <details class="card compact-details">
          <summary>Fix commands</summary>
          <div class="compact-details-body">${doctorFixList(issues)}</div>
        </details>
      </div>
    </div>`;
}
function doctorSummary(checks){
  const summary = {total:(checks||[]).length, ok:0, warn:0, fail:0, info:0, pending:0, areas:0};
  const areas = new Set();
  (checks||[]).forEach(c => {
    const key = c.status || 'info';
    summary[key] = (summary[key] || 0) + 1;
    if(c.area) areas.add(c.area);
  });
  summary.areas = areas.size;
  return summary;
}
function doctorKpi(label, value, hint){
  return `<div class="doctor-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint||'')}</div></div>`;
}
function doctorStatusFilters(summary){
  const items = [['all', summary.total], ['fail', summary.fail], ['warn', summary.warn], ['ok', summary.ok]];
  return items.map(([key,count]) => `<button class="filter-pill ${state.doctorStatus===key?'active':''}" onclick="setDoctorFilter('${key}',state.doctorArea)">${esc(key==='all'?'All':key)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function setDoctorFilter(statusValue, areaValue){
  state.doctorStatus = statusValue || 'all';
  state.doctorArea = areaValue || 'all';
  doctor();
}
function filterDoctorChecks(checks){
  return (checks || []).filter(c => (state.doctorStatus === 'all' || c.status === state.doctorStatus) && (state.doctorArea === 'all' || c.area === state.doctorArea));
}
function doctorIssueList(checks){
  if(!(checks||[]).length) return '<div class="empty-state">No fail or warn checks</div>';
  return `<div class="issue-list">${checks.map(c => `<div class="issue-item ${esc(c.status)}"><div class="section-title"><div><div class="check-title">${esc(c.name)}</div><div class="item-meta">${esc(c.area)}</div></div>${status(c.status)}</div><div class="check-message">${esc(c.message)}</div>${c.fix?`<div class="fix-command">${esc(c.fix)}</div>`:''}</div>`).join('')}</div>`;
}
function doctorCheckList(checks){
  if(!(checks||[]).length) return '<div class="empty-state">No checks match this filter</div>';
  return `<div class="check-list">${checks.map(c => `<div class="check-row"><div>${status(c.status)}</div><div class="item-meta">${esc(c.area)}</div><div><div class="check-title">${esc(c.name)}</div><div class="check-message">${esc(c.message)}</div>${c.fix?`<div class="fix-command">${esc(c.fix)}</div>`:''}</div></div>`).join('')}</div>`;
}
function doctorAreaList(checks){
  const areaMap = {};
  (checks || []).forEach(c => {
    const area = c.area || 'other';
    areaMap[area] = areaMap[area] || {total:0, fail:0, warn:0, ok:0};
    areaMap[area].total += 1;
    areaMap[area][c.status] = (areaMap[area][c.status] || 0) + 1;
  });
  const rows = [['all', doctorSummary(checks)], ...Object.entries(areaMap).sort(([a],[b]) => a.localeCompare(b))];
  return `<div class="area-list">${rows.map(([area,counts]) => `<div class="area-row ${state.doctorArea===area?'active':''}" onclick="setDoctorFilter(state.doctorStatus,'${escAttr(area)}')"><b>${esc(area==='all'?'All':area)}</b><span class="area-counts"><span>${esc(counts.total)} total</span><span>${esc(counts.fail||0)} fail</span><span>${esc(counts.warn||0)} warn</span></span></div>`).join('')}</div>`;
}
function doctorFixList(checks){
  const fixes = (checks || []).filter(c => c.fix).slice(0, 8);
  if(!fixes.length) return '<div class="empty-state">No fix commands needed</div>';
  return `<div class="fix-list">${fixes.map(c => `<div class="fix-item"><div class="check-title">${esc(c.name)}</div><div class="item-meta">${esc(c.area)} · ${esc(c.status)}</div><div class="fix-command">${esc(c.fix)}</div></div>`).join('')}</div>`;
}
async function audio(){
  setHeader('音频队列','读取中...',
    `<button class="btn primary" onclick="action('analyze_audio',{limit:5})">分析 5 条</button><button class="btn" onclick="action('analyze_audio',{limit:20})">分析 20 条</button><button class="btn" onclick="audio()">刷新</button>`);
  const qs = state.audioStatus ? `?status=${encodeURIComponent(state.audioStatus)}&limit=180` : '?limit=180';
  const j=await api('/api/audio'+qs);
  const summary = j.summary || {};
  const statuses = summary.statuses || {};
  const items = j.items || [];
  const selected = state.audioStatus || 'all';
  const pending = statuses.pending || 0;
  const errors = statuses.error || 0;
  const attention = audioAttentionCount(statuses);
  const coverage = summary.total ? Math.round((Number(summary.with_summary || 0) / Number(summary.total || 1)) * 100) : 0;
  const priority = items.filter(a => audioNeedsAttention(a.status)).slice(0, 8);
  $('subtitle').textContent = `${summary.total || 0} total · ${pending} pending · ${attention} attention · ${selected}`;
  $('view').innerHTML = `
    <div class="audio-hero">
      <div class="card">
        <div class="section-title"><h3>队列状态</h3>${status(errors ? 'error' : attention ? 'pending' : 'ok')}</div>
        <div class="audio-kpis">
          ${audioKpi('Total', summary.total || 0, 'mobile/audio_segment')}
          ${audioKpi('Pending', pending, 'waiting analysis')}
          ${audioKpi('Attention', attention, 'non-ok status')}
          ${audioKpi('Summary', `${summary.with_summary || 0}/${summary.total || 0}`, `${coverage}% covered`)}
        </div>
        <div class="audio-filters">${audioStatusFilters(statuses, summary.total || 0)}</div>
      </div>
      <div class="card">
        <div class="section-title"><h3>批处理</h3><span class="muted">${esc(summary.latest_analyzed || 'not analyzed')}</span></div>
        <div class="overview-actions">
          <button class="btn primary" onclick="action('analyze_audio',{limit:5})">分析 5 条</button>
          <button class="btn" onclick="action('analyze_audio',{limit:20})">分析 20 条</button>
          <button class="btn" onclick="action('analyze_audio',{limit:50})">分析 50 条</button>
          <button class="btn" onclick="go('sync')">手机同步</button>
        </div>
      </div>
    </div>
    <div class="audio-main">
      <div class="grid">
        ${priority.length ? `<div class="card">
          <div class="section-title"><h3>优先处理</h3><span class="muted">${esc(priority.length)} shown</span></div>
          ${audioPriorityList(priority)}
        </div>` : ''}
        <div class="card">
          <div class="section-title"><h3>队列明细</h3><span class="muted">${esc(items.length)} loaded</span></div>
          ${audioQueueList(items)}
        </div>
      </div>
      <div class="audio-side">
        <div class="card">
          <div class="section-title"><h3>状态分布</h3><span class="muted">${esc(selected)}</span></div>
          ${audioStatusBreakdown(statuses, summary.total || 0)}
        </div>
        <div class="card">
          <div class="section-title"><h3>覆盖率</h3></div>
          <div class="overview-queue">
            <div class="queue-row"><span>With summary</span><span class="queue-value">${esc(summary.with_summary || 0)}</span></div>
            <div class="queue-row"><span>With transcript/body</span><span class="queue-value">${esc(summary.with_body || 0)}</span></div>
            <div class="queue-row"><span>Latest analyzed</span><span class="queue-value">${esc(shortDateTime(summary.latest_analyzed || '-'))}</span></div>
          </div>
        </div>
      </div>
    </div>`;
}
function audioKpi(label, value, hint){
  return `<div class="audio-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint||'')}</div></div>`;
}
function audioStatusFilters(statuses, total){
  const keys = ['all', ...Object.keys(statuses || {}).sort((a,b) => audioStatusRank(a) - audioStatusRank(b) || a.localeCompare(b))];
  return keys.map(key => {
    const count = key === 'all' ? total : statuses[key];
    const active = (key === 'all' && !state.audioStatus) || state.audioStatus === key;
    const next = key === 'all' ? '' : key;
    return `<button class="filter-pill ${active?'active':''}" onclick="setAudioStatus('${escAttr(next)}')">${esc(key)} <span class="chip-count">${esc(count || 0)}</span></button>`;
  }).join('');
}
function setAudioStatus(value){
  state.audioStatus = value || '';
  audio();
}
function audioStatusRank(value){
  return ({error:0,missing_file:1,pending:2,processing:3,ok:4,skipped:5})[value] ?? 8;
}
function audioNeedsAttention(statusValue){
  const key = String(statusValue || 'pending');
  return !['ok','skipped'].includes(key);
}
function audioAttentionCount(statuses){
  return Object.entries(statuses || {}).reduce((total, [key, count]) => total + (audioNeedsAttention(key) ? Number(count || 0) : 0), 0);
}
function audioPriorityList(rows){
  return (rows || []).length ? `<div class="audio-priority">${rows.map(audioCard).join('')}</div>` : '<div class="empty-state">No non-ok audio in the current view</div>';
}
function audioQueueList(rows){
  return (rows || []).length ? `<div class="audio-list">${rows.map(audioCard).join('')}</div>` : '<div class="empty-state">No audio records match this filter</div>';
}
function audioCard(a){
  const text = a.error || a.summary || a.body_preview || 'No summary yet';
  const speakers = (a.speakers || []).length ? ` · ${a.speakers.join(' · ')}` : '';
  return `<div class="audio-card ${esc(a.status || 'pending')}">
    <div class="audio-time">${esc(shortDateTime(a.observed_at))}${a.captured_at?`<br><span class="muted">captured ${esc(shortDateTime(a.captured_at))}</span>`:''}</div>
    <div>${status(a.status || 'pending')}<div class="item-meta">${esc(formatSeconds(a.duration_seconds))}</div></div>
    <div><div class="audio-title">${esc(a.title || a.kind || 'Audio segment')}</div><div class="item-meta">${esc(a.source || '')}/${esc(a.kind || '')}${a.transcript_status?' · '+esc(a.transcript_status):''}${esc(speakers)}</div><div class="audio-body">${esc(text)}</div>${a.media_path?`<div class="audio-path">${esc(shortPath(a.media_path))}</div>`:''}</div>
  </div>`;
}
function audioStatusBreakdown(statuses, total){
  const keys = Object.keys(statuses || {}).sort((a,b) => audioStatusRank(a) - audioStatusRank(b) || a.localeCompare(b));
  if(!keys.length) return '<div class="empty-state">No audio statuses</div>';
  return `<div class="status-breakdown">${keys.map(key => `<div class="status-row"><span>${status(key)}</span><span class="queue-value">${esc(statuses[key])}</span></div>`).join('')}<div class="status-row"><span>Total</span><span class="queue-value">${esc(total)}</span></div></div>`;
}
function formatSeconds(value){
  const n = Number(value || 0);
  if(!Number.isFinite(n) || n <= 0) return '-';
  const total = Math.round(n);
  const min = Math.floor(total / 60);
  const sec = String(total % 60).padStart(2, '0');
  return `${min}:${sec}`;
}
async function search(){
  setHeader('资料问答','本地检索、语义召回和证据问答', `<button class="btn" onclick="refreshSearchIndex()">索引状态</button><button class="btn primary" onclick="action('search_index',{limit:5000,force:true})">重建语义索引</button>`);
  $('view').innerHTML = `<div class="search-hero">
    <div class="card">
      <div class="section-title"><h3>问答工作区</h3>${status('info')}</div>
      <div class="searchbar">
        <input id="q" value="${esc(state.searchQ)}" placeholder="关键词或问题" oninput="state.searchQ=this.value" onkeydown="searchKey(event)" aria-label="search">
        <select id="src" onchange="setSearchSource(this.value)">${searchSourceOptions(state.searchSource)}</select>
        <button class="btn primary" onclick="doSearch()">搜索</button>
        <button class="btn" onclick="doAsk()">问答</button>
      </div>
      <textarea id="question" placeholder="向本地资料提问，例如：今天录音里有什么值得跟进？" oninput="state.searchQuestion=this.value">${esc(state.searchQuestion)}</textarea>
      <div class="search-actions">
        <button class="btn primary" onclick="doAsk()">问本地资料</button>
        <button class="btn" onclick="doSearch()">只搜索</button>
      </div>
    </div>
    <div class="search-side">
      <div class="card">
        <div class="section-title"><h3>语义索引</h3><span class="muted">local</span></div>
        <div id="indexStatus" class="muted">Loading...</div>
      </div>
      <div class="card">
        <div class="section-title"><h3>来源</h3><span id="searchSourceLabel" class="muted">${esc(searchSourceLabel(state.searchSource))}</span></div>
        ${searchSourcePills(state.searchSource)}
      </div>
    </div>
  </div>
  <div id="searchResults"></div>`;
  refreshSearchIndex();
}
async function refreshSearchIndex(){
  const j=await api('/api/search-index');
  const index=j.index || {};
  if(!$('indexStatus')) return;
  const models = index.models || [];
  const latest = models[0] || {};
  const coverage = index.coverage || {};
  const coveragePct = Math.round(Number(coverage.coverage || 0) * 100);
  const sourceRows = (coverage.by_source || []).slice(0, 8);
  $('indexStatus').innerHTML = `<div class="search-index-grid">
    <div class="search-index-stat"><div class="label">Vectors</div><div class="value">${esc(index.total_embeddings || 0)}</div></div>
    <div class="search-index-stat"><div class="label">Model</div><div class="value compact">${esc(shortModelName(latest.model || index.configured_model || '(auto)'))}</div></div>
    <div class="search-index-stat"><div class="label">Coverage</div><div class="value">${esc(coveragePct)}%</div></div>
    <div class="search-index-stat"><div class="label">Missing</div><div class="value">${esc(coverage.missing_observations || 0)}</div></div>
  </div>
  <div style="margin-top:10px">${sourceRows.map(row => `<div class="search-model-row"><div class="item-title">${esc(row.source)}/${esc(row.kind)}</div><div class="item-meta">${esc(row.indexed || 0)} / ${esc(row.total || 0)} indexed · priority ${esc(row.priority || 0)} · latest ${esc(shortDateTime(row.latest_observed || ''))}</div></div>`).join('') || '<div class="empty-state">No source coverage</div>'}</div>
  <div style="margin-top:10px">${models.map(m => `<div class="search-model-row"><div class="item-title">${esc(m.model)}</div><div class="item-meta">${esc(m.count)} vectors · ${esc(shortDateTime(m.latest || ''))}</div></div>`).join('') || '<div class="empty-state">No vectors</div>'}</div>
  <div class="item-meta">limit ${esc(index.index_limit || '-')} · auto ${esc(index.auto_index_limit || 0)} · candidates ${(index.candidate_models || []).slice(0, 3).map(esc).join(', ')}</div>`;
}
async function doSearch(){
  syncSearchState();
  const q=state.searchQ, src=state.searchSource;
  $('searchResults').innerHTML = searchLoading('Searching local memory...');
  const j=await api(`/api/search?q=${encodeURIComponent(q)}&source=${encodeURIComponent(src)}&limit=80`);
  $('searchResults').innerHTML = `${searchRetrievalCard(j)}
    <div class="search-main">
      <div class="card">
        <div class="section-title"><h3>语义结果</h3><span class="muted">${esc((j.semantic || []).length)} matches</span></div>
        ${searchSemanticList(j.semantic)}
      </div>
      <div class="search-stack">
        <div class="card">
          <div class="section-title"><h3>关键词记录</h3><span class="muted">${esc((j.observations || []).length)} records</span></div>
          ${searchObservationList(j.observations)}
        </div>
        <div class="card">
          <div class="section-title"><h3>报告</h3><span class="muted">${esc((j.reports || []).length)} files</span></div>
          ${searchReportList(j.reports)}
        </div>
      </div>
    </div>`;
}
async function doAsk(){
  syncSearchState();
  const question=(state.searchQuestion || state.searchQ || '').trim();
  if(!question){
    $('searchResults').innerHTML = `<div class="card" style="margin-top:14px"><div class="empty-state">No question yet</div></div>`;
    return;
  }
  $('searchResults').innerHTML = searchLoading('Retrieving evidence and asking the local model...');
  const j=await api('/api/ask',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({question})});
  state.searchQuestion = question;
  $('searchResults').innerHTML = `<div class="search-answer-layout">
    <div class="card answer">
      <div class="section-title"><h3>答案</h3>${status(j.mode)}</div>
      <div class="result-meta"><span>retrieval ${esc((j.retrieval||{}).status||'')}</span><span>model ${esc((j.retrieval||{}).model||'')}</span>${(j.time_context||{}).now?`<span>${esc(shortDateTime(j.time_context.now))}</span>`:''}</div>
      <div class="answer-body" style="margin-top:12px">${esc(j.answer).replace(/\n/g,'<br>')}</div>
    </div>
    <div class="search-answer-side">
      <div class="card">
        <div class="section-title"><h3>检索</h3>${status((j.retrieval||{}).status||'keyword')}</div>
        <div class="search-metric-grid">
          ${searchMetric('Mode', (j.retrieval||{}).mode || j.mode || '-')}
          ${searchMetric('Indexed', (j.retrieval||{}).indexed || 0)}
        </div>
        ${(j.retrieval||{}).error?`<div class="search-error">${esc((j.retrieval||{}).error)}</div>`:''}
      </div>
      <div class="card">
        <div class="section-title"><h3>引用</h3><span class="muted">${esc((j.citations || []).length)} items</span></div>
        ${citationList(j.citations)}
      </div>
      <div class="card">
        <div class="section-title"><h3>证据分组</h3><span class="muted">${esc(evidenceGroupTotal(j.evidence_groups))} items</span></div>
        ${evidenceGroupsPanel(j.evidence_groups)}
      </div>
    </div>
  </div>`;
}
function syncSearchState(){
  if($('q')) state.searchQ = $('q').value;
  if($('src')) state.searchSource = $('src').value;
  if($('question')) state.searchQuestion = $('question').value;
}
function searchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    doSearch();
  }
}
function searchSourceOptions(selected){
  return searchSources.map(([value, label]) => `<option value="${escAttr(value)}" ${selected===value?'selected':''}>${esc(label)}</option>`).join('');
}
function searchSourcePills(selected){
  return `<div class="search-source-pills">${searchSources.map(([value, label]) => `<button data-search-source="${escAttr(value)}" class="filter-pill ${selected===value?'active':''}" onclick="setSearchSource('${escAttr(value)}')">${esc(label)}</button>`).join('')}</div>`;
}
function setSearchSource(value){
  state.searchSource = value || '';
  if($('src')) $('src').value = state.searchSource;
  if($('searchSourceLabel')) $('searchSourceLabel').textContent = searchSourceLabel(state.searchSource);
  document.querySelectorAll('[data-search-source]').forEach(btn => btn.classList.toggle('active', (btn.getAttribute('data-search-source') || '') === state.searchSource));
}
function searchSourceLabel(value){
  const found = searchSources.find(([source]) => source === value);
  return found ? found[1] : value || '全部来源';
}
function searchLoading(text){
  return `<div class="card" style="margin-top:14px"><div class="empty-state">${esc(text)}</div></div>`;
}
function searchRetrievalCard(j){
  const retrieval = j.retrieval || {};
  return `<div class="card search-retrieval">
    <div>
      <div class="section-title"><h3>检索概览</h3>${status(retrieval.status || 'keyword')}</div>
      <div class="result-meta">
        <span>query ${esc(j.query || state.searchQ || '-')}</span>
        <span>source ${esc(searchSourceLabel(state.searchSource))}</span>
        <span>mode ${esc(retrieval.mode || '-')}</span>
        <span>model ${esc(retrieval.model || '-')}</span>
      </div>
      ${retrieval.error ? `<div class="search-error">${esc(retrieval.error)}</div>` : ''}
    </div>
    <div class="search-metric-grid">
      ${searchMetric('Semantic', (j.semantic || []).length)}
      ${searchMetric('Keyword', (j.observations || []).length)}
      ${searchMetric('Reports', (j.reports || []).length)}
      ${searchMetric('Indexed', retrieval.indexed || 0)}
    </div>
  </div>`;
}
function searchMetric(label, value){
  return `<div class="search-metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}
function searchSemanticList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No semantic matches</div>';
  return `<div class="search-list">${rows.map(r => `<div class="search-result semantic">
    <div class="result-title">${esc(r.title || r.key || 'Semantic match')}</div>
    <div class="result-meta"><span>score ${esc(formatScore(r.score))}</span><span>${esc(shortDateTime(r.observed_at || ''))}</span><span>${esc(r.source || '')}/${esc(r.kind || '')}</span></div>
    <div class="result-text">${esc(r.text || '')}</div>
  </div>`).join('')}</div>`;
}
function searchObservationList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No keyword records</div>';
  return `<div class="search-list">${rows.map(o => `<div class="search-result observation">
    <div class="result-title">${esc(o.title || o.subtitle || o.kind || o.name || 'Record')}</div>
    <div class="result-meta"><span>${esc(shortDateTime(o.observed_at || o.modified_at || ''))}</span><span>${esc(o.source || o.category || '')}/${esc(o.kind || '')}</span></div>
    <div class="result-text">${esc(o.body || o.summary || o.snippet || '')}</div>
  </div>`).join('')}</div>`;
}
function searchReportList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No reports</div>';
  return `<div class="search-list">${rows.map(r => `<div class="search-result report">
    <div class="result-title">${esc(r.name || 'Report')}</div>
    <div class="result-meta"><span>${esc(r.category || '')}</span><span>${esc(shortDateTime(r.modified_at || ''))}</span></div>
    <div class="result-text">${esc(r.snippet || '')}</div>
  </div>`).join('')}</div>`;
}
function citationList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No citations</div>';
  return `<div class="citation-list">${rows.map(c => `<div class="citation-row">
    <div class="citation-type">${esc(c.type || 'evidence')}</div>
    <div class="item-meta">${citationMeta(c).map(esc).join(' · ')}</div>
    <div class="result-text">${esc(c.name || c.path || c.key || c.id || '')}</div>
  </div>`).join('')}</div>`;
}
function citationMeta(c){
  const parts = [];
  if(c.time) parts.push(shortDateTime(c.time));
  if(c.source || c.kind) parts.push(`${c.source || ''}/${c.kind || ''}`);
  if(c.score !== undefined && c.score !== null) parts.push(`score ${formatScore(c.score)}`);
  if(c.date_context) parts.push(c.date_context);
  return parts;
}
function evidenceGroupTotal(payload){
  const counts = (payload || {}).counts || {};
  return Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0);
}
function evidenceGroupsPanel(payload){
  const groups = (payload || {}).groups || {};
  const keys = Object.keys(groups);
  if(!keys.length) return '<div class="empty-state">No grouped evidence</div>';
  return `<div class="evidence-groups">${keys.map(key => `<div class="evidence-group">
    <div class="section-title"><h3>${esc(evidenceGroupLabel(key))}</h3><span class="muted">${esc((groups[key] || []).length)}</span></div>
    ${(groups[key] || []).slice(0, 5).map(evidenceItem).join('')}
  </div>`).join('')}</div>`;
}
function evidenceItem(item){
  return `<div class="evidence-item">
    <div class="result-title">${esc(item.title || item.id || 'Evidence')}</div>
    <div class="result-meta"><span>${esc(shortDateTime(item.time || ''))}</span><span>${esc(item.source || '')}/${esc(item.kind || '')}</span>${item.score !== undefined && item.score !== null ? `<span>score ${esc(formatScore(item.score))}</span>` : ''}</div>
    <div class="result-text">${esc(item.snippet || item.location || item.path || '')}</div>
  </div>`;
}
function evidenceGroupLabel(key){
  return ({timeline:'时间线',audio:'录音',location:'位置',files:'文件',reports:'报告',semantic:'语义',feedback:'反馈'})[key] || key;
}
function formatScore(value){
  const n = Number(value);
  return Number.isFinite(n) ? n.toFixed(3) : (value ?? '-');
}
function normalizeSpeakerThresholds(raw={}){
  const autoMerge = Number(raw.auto_merge_threshold ?? raw.autoMergeThreshold);
  const candidate = Number(raw.candidate_threshold ?? raw.candidateThreshold);
  const review = Number(raw.review_min_confidence ?? raw.reviewMinConfidence);
  return {
    auto_merge_threshold: Number.isFinite(autoMerge) && autoMerge > 0 && autoMerge <= 1 ? autoMerge : 0.68,
    candidate_threshold: Number.isFinite(candidate) && candidate > 0 && candidate <= 1 ? candidate : 0.68,
    review_min_confidence: Number.isFinite(review) && review > 0 && review <= 1 ? review : 0.90,
  };
}
function updateSpeakerThresholds(raw={}){
  state.speakerThresholds = normalizeSpeakerThresholds(raw);
  return state.speakerThresholds;
}
function speakerThresholds(){
  return normalizeSpeakerThresholds(state.speakerThresholds || {});
}
function speakerAutoMergeThreshold(){
  return speakerThresholds().auto_merge_threshold;
}
function speakerLowConfidenceThreshold(){
  return speakerThresholds().candidate_threshold;
}
function shortModelName(value){
  const text = String(value || '');
  return text.endsWith(':latest') ? text.slice(0, -7) : text;
}
async function timeline(){
  setHeader('时间线','按日期查看本地事件流', `<button class="btn" onclick="setTimelineDate('today')">今天</button><button class="btn" onclick="setTimelineDate('yesterday')">昨天</button><button class="btn primary" onclick="timeline()">Refresh</button>`);
  const j=await api(`/api/timeline?date=${encodeURIComponent(state.timelineDate)}`);
  const allEvents = j.events || [];
  const events = filterTimelineEvents(allEvents);
  const sourceCounts = countBy(allEvents, event => event.source || 'unknown');
  const typeCounts = countBy(allEvents, event => event.type || 'unknown');
  const statusCounts = countBy(allEvents.filter(event => event.status), event => event.status || 'unknown');
  const sources = Object.keys(sourceCounts).sort((a,b) => sourceCounts[b] - sourceCounts[a] || a.localeCompare(b));
  const types = Object.keys(typeCounts).sort((a,b) => typeCounts[b] - typeCounts[a] || a.localeCompare(b));
  const range = shortRange(allEvents[0]?.time, allEvents[allEvents.length - 1]?.time);
  $('subtitle').textContent = `${j.date} · ${events.length}/${allEvents.length} 条 · ${range}`;
  $('view').innerHTML = `
    <div class="timeline-hero">
      <div class="card">
        <div class="section-title"><h3>筛选</h3><span class="muted">${esc(j.date)}</span></div>
        <div class="timeline-toolbar">
          <input id="tlDate" value="${esc(state.timelineDate)}" aria-label="date">
          <input id="tlQ" value="${esc(state.timelineQ)}" placeholder="筛选标题、正文、source/kind" aria-label="search" onkeydown="timelineKey(event)">
          <select id="tlSource">${timelineSourceOptions(sources)}</select>
          <select id="tlType">${timelineTypeOptions(types)}</select>
          <button class="btn primary" onclick="applyTimelineFilters()">查找</button>
        </div>
        <div class="quickbar" style="margin-top:10px">
          <button class="filter-pill ${state.timelineDate==='today'?'active':''}" onclick="setTimelineDate('today')">今天</button>
          <button class="filter-pill ${state.timelineDate==='yesterday'?'active':''}" onclick="setTimelineDate('yesterday')">昨天</button>
          <button class="filter-pill ${!state.timelineQ && state.timelineSource==='all' && state.timelineType==='all'?'active':''}" onclick="resetTimelineFilters()">全部事件</button>
          <button class="filter-pill ${state.timelineType==='observation'?'active':''}" onclick="setTimelineType('observation')">Observation</button>
          <button class="filter-pill ${state.timelineType==='activity'?'active':''}" onclick="setTimelineType('activity')">Activity</button>
        </div>
        <div class="timeline-stats">
          ${timelineStat('事件', allEvents.length, `${events.length} 条显示`)}
          ${timelineStat('Observation', typeCounts.observation || 0, 'records')}
          ${timelineStat('Activity', typeCounts.activity || 0, 'foreground app')}
          ${timelineStat('来源', sources.length, range)}
        </div>
        ${hourBars(allEvents)}
      </div>
      <div class="card">
        <div class="section-title"><h3>来源</h3><span class="muted">${esc(state.timelineSource === 'all' ? '全部来源' : state.timelineSource)}</span></div>
        ${timelineBreakdown(sourceCounts, state.timelineSource, 'source')}
      </div>
    </div>
    <div class="timeline-main">
      <div>
        <div class="section-title"><h3>事件流</h3><span class="muted">${esc(events.length)} shown</span></div>
        <div class="timeline-feed">${timelineSections(events)}</div>
      </div>
      <div class="timeline-side">
        <div class="card">
          <div class="section-title"><h3>类型</h3><span class="muted">${esc(state.timelineType)}</span></div>
          ${timelineBreakdown(typeCounts, state.timelineType, 'type')}
        </div>
        <div class="card">
          <div class="section-title"><h3>状态</h3><span class="muted">${esc(Object.keys(statusCounts).length || 0)}</span></div>
          ${Object.keys(statusCounts).length ? timelineBreakdown(statusCounts, 'all', 'status') : '<div class="empty-state">No status tags</div>'}
        </div>
        <div class="card">
          <div class="section-title"><h3>当前筛选</h3></div>
          <div class="overview-queue">
            <div class="queue-row"><span>Date</span><span class="queue-value">${esc(j.date)}</span></div>
            <div class="queue-row"><span>Source</span><span class="queue-value">${esc(state.timelineSource)}</span></div>
            <div class="queue-row"><span>Type</span><span class="queue-value">${esc(state.timelineType)}</span></div>
            <div class="queue-row"><span>Query</span><span class="queue-value">${esc(state.timelineQ || '-')}</span></div>
          </div>
        </div>
      </div>
    </div>`;
}
function applyTimelineFilters(){
  state.timelineDate = $('tlDate').value || 'today';
  state.timelineQ = $('tlQ').value;
  state.timelineSource = $('tlSource').value || 'all';
  state.timelineType = $('tlType').value || 'all';
  timeline();
}
function timelineKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyTimelineFilters();
  }
}
function setTimelineDate(value){
  state.timelineDate = value || 'today';
  timeline();
}
function setTimelineSource(value){
  state.timelineSource = value || 'all';
  timeline();
}
function setTimelineType(value){
  state.timelineType = value || 'all';
  timeline();
}
function resetTimelineFilters(){
  state.timelineQ = '';
  state.timelineSource = 'all';
  state.timelineType = 'all';
  timeline();
}
function filterTimelineEvents(rows){
  const q = String(state.timelineQ || '').trim().toLowerCase();
  return (rows || []).filter(event => {
    if(state.timelineSource && state.timelineSource !== 'all' && event.source !== state.timelineSource) return false;
    if(state.timelineType && state.timelineType !== 'all' && event.type !== state.timelineType) return false;
    if(!q) return true;
    const haystack = [event.time, event.type, event.source, event.kind, event.title, event.body, event.status].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function timelineSourceOptions(sources){
  const values = ['all', ...sources];
  if(state.timelineSource && !values.includes(state.timelineSource)) values.push(state.timelineSource);
  return values.map(value => `<option value="${escAttr(value)}" ${state.timelineSource===value?'selected':''}>${esc(value === 'all' ? '全部来源' : value)}</option>`).join('');
}
function timelineTypeOptions(types){
  const values = ['all', ...types];
  if(state.timelineType && !values.includes(state.timelineType)) values.push(state.timelineType);
  return values.map(value => `<option value="${escAttr(value)}" ${state.timelineType===value?'selected':''}>${esc(value === 'all' ? '全部类型' : value)}</option>`).join('');
}
function timelineStat(label, value, hint){
  return `<div class="timeline-stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function countBy(rows, keyFn){
  return (rows || []).reduce((acc, row) => {
    const key = String(keyFn(row) || 'unknown');
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
}
function timelineBreakdown(counts, active, kind){
  const rows = Object.entries(counts || {}).sort(([,a],[,b]) => Number(b||0) - Number(a||0));
  if(!rows.length) return '<div class="empty-state">No records</div>';
  const total = rows.reduce((sum, [,count]) => sum + Number(count || 0), 0);
  const allActive = !active || active === 'all';
  const allClick = kind === 'source' ? "setTimelineSource('all')" : kind === 'type' ? "setTimelineType('all')" : '';
  return `<div class="timeline-breakdown">
    ${kind === 'status' ? '' : `<div class="timeline-breakdown-row ${allActive?'active':''}" onclick="${allClick}"><span>全部</span><span class="queue-value">${esc(total)}</span></div>`}
    ${rows.map(([key,count]) => {
      const click = kind === 'source' ? `setTimelineSource('${escAttr(key)}')` : kind === 'type' ? `setTimelineType('${escAttr(key)}')` : '';
      return `<div class="timeline-breakdown-row ${active===key?'active':''}" ${click?`onclick="${click}"`:''}><span>${esc(key)}</span><span class="queue-value">${esc(count)}</span></div>`;
    }).join('')}
  </div>`;
}
function timelineSections(rows){
  if(!(rows || []).length) return '<div class="empty-state">No timeline events match this filter</div>';
  const groups = {late: [], morning: [], afternoon: [], evening: [], night: []};
  (rows || []).forEach(event => groups[dayPartKey(event.time)].push(event));
  return ['late','morning','afternoon','evening','night']
    .filter(key => groups[key].length)
    .map(key => `<section class="timeline-section"><div class="timeline-section-header"><h3>${esc(dayPartLabel(key))}</h3><span class="muted">${groups[key].length} 条 · ${esc(shortRange(groups[key][0].time, groups[key][groups[key].length - 1].time))}</span></div><div class="timeline-list">${groups[key].map(timelineEventCard).join('')}</div></section>`)
    .join('');
}
function timelineEventCard(e){
  return `<div class="timeline-event ${esc(e.type || 'observation')}">
    <div class="timeline-time">${esc(shortTime(e.time))}</div>
    <div>${status(e.type || 'event')}${e.status?`<div style="margin-top:6px">${status(e.status)}</div>`:''}</div>
    <div><div class="timeline-title">${esc(e.title || e.kind || 'Event')}</div><div class="timeline-meta"><span>${esc(e.source || '')}/${esc(e.kind || '')}</span><span>${esc(shortDateTime(e.time))}</span></div>${e.body?`<div class="timeline-body">${esc(e.body)}</div>`:''}</div>
  </div>`;
}
async function reports(){
  setHeader('报告','日报、长期摘要、邮件摘要和反馈记录', `<button class="btn primary" onclick="action('refresh_report',{date:'today'})">刷新今日报告</button><button class="btn" onclick="action('compact',{date:'today',period:'all'})">压缩摘要</button><button class="btn" onclick="go('today')">今天</button><button class="btn" onclick="reports()">刷新</button>`);
  const suffix = state.reportPath ? `?path=${encodeURIComponent(state.reportPath)}` : '';
  const j=await api('/api/reports'+suffix);
  const files = j.files || [];
  const selectedPath = j.selected || state.reportPath || (files[0] || {}).path || '';
  if(selectedPath && state.reportPath !== selectedPath) state.reportPath = selectedPath;
  const selectedFile = files.find(file => file.path === selectedPath) || files[0] || {};
  const filteredFiles = filterReportFiles(files);
  const categoryCounts = countBy(files, file => file.category || 'reports');
  const headings = reportHeadings(j.content || '');
  const stats = reportStats(j.content || '');
  $('subtitle').textContent = selectedFile.name ? `${selectedFile.name} · ${escText(reportCategoryLabel(selectedFile.category))} · ${bytes(selectedFile.size || 0)}` : `${files.length} files`;
  $('view').innerHTML = `<div class="reports-layout">
    <div class="reports-nav">
      <div class="card reports-controls">
        <div class="section-title"><h3>报告库</h3><span class="muted">${esc(filteredFiles.length)}/${esc(files.length)}</span></div>
        <input id="reportQ" value="${esc(state.reportQ)}" placeholder="搜索文件名、分类、路径" onkeydown="reportSearchKey(event)" aria-label="report search">
        <button class="btn primary" onclick="applyReportSearch()">查找</button>
      </div>
      <div class="card">
        <div class="section-title"><h3>文件</h3><span class="muted">${esc(reportCategoryLabel(state.reportCategory))}</span></div>
        ${reportFileList(filteredFiles, selectedPath)}
      </div>
    </div>
    <div class="card report-reader">
      ${reportReader(selectedFile, j.content || '')}
    </div>
    <div class="reports-side">
      <div class="card">
        <div class="section-title"><h3>当前文件</h3>${selectedFile.category?reportCategoryBadge(selectedFile.category):status('empty')}</div>
        <div class="reports-metrics">
          ${reportMetric('Size', bytes(selectedFile.size || 0))}
          ${reportMetric('Lines', stats.lines)}
          ${reportMetric('Headings', headings.length)}
          ${reportMetric('Words', stats.words)}
        </div>
        <div class="item-meta" style="margin-top:10px">${esc(shortDateTime(selectedFile.modified_at || ''))}</div>
        <div class="item-meta">${esc(selectedFile.path || '')}</div>
      </div>
      <div class="card">
        <div class="section-title"><h3>分类</h3><span class="muted">${esc(reportCategoryLabel(state.reportCategory))}</span></div>
        ${reportCategoryBreakdown(categoryCounts, files.length)}
      </div>
      <div class="card">
        <div class="section-title"><h3>大纲</h3><span class="muted">${esc(headings.length)} headings</span></div>
        ${reportOutline(headings)}
      </div>
    </div>
  </div>`;
}
function applyReportSearch(){
  state.reportQ = $('reportQ').value;
  reports();
}
function reportSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyReportSearch();
  }
}
function setReportPath(path){
  state.reportPath = path || '';
  reports();
}
function setReportCategory(category){
  state.reportCategory = category || 'all';
  reports();
}
function filterReportFiles(files){
  const q = String(state.reportQ || '').trim().toLowerCase();
  return (files || []).filter(file => {
    if(state.reportCategory && state.reportCategory !== 'all' && file.category !== state.reportCategory) return false;
    if(!q) return true;
    const haystack = [file.name, file.category, file.path, file.modified_at].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function reportFileList(files, selectedPath){
  if(!(files || []).length) return '<div class="empty-state">No reports match this filter</div>';
  return `<div class="reports-list">${files.map(file => `<div class="report-file-item ${file.path===selectedPath?'active':''}" onclick="setReportPath('${escAttr(file.path)}')">
    <div class="report-file-title">${esc(file.name)}</div>
    <div class="report-file-meta"><span>${esc(reportCategoryLabel(file.category))}</span><span>${esc(bytes(file.size || 0))}</span><span>${esc(shortDateTime(file.modified_at || ''))}</span></div>
  </div>`).join('')}</div>`;
}
function reportCategoryBreakdown(counts, total){
  const order = ['all','reports','daily','weekly','monthly','email','feedback'];
  const keys = [...order, ...Object.keys(counts || {}).filter(key => !order.includes(key)).sort()];
  return `<div class="report-category-list">${keys.map(key => {
    const count = key === 'all' ? total : Number((counts || {})[key] || 0);
    if(key !== 'all' && count <= 0) return '';
    return `<div class="report-category-row ${state.reportCategory===key?'active':''}" onclick="setReportCategory('${escAttr(key)}')"><span>${esc(reportCategoryLabel(key))}</span><span class="queue-value">${esc(count)}</span></div>`;
  }).join('')}</div>`;
}
function reportReader(file, content){
  if(!content) return '<div class="empty-state">No report content</div>';
  return `<div class="report-reader-header">
    <div class="report-reader-title">${esc(file.name || 'Report')}</div>
    <div class="result-meta"><span>${esc(reportCategoryLabel(file.category))}</span><span>${esc(shortDateTime(file.modified_at || ''))}</span><span>${esc(bytes(file.size || 0))}</span></div>
  </div>
  <div class="report-reader-content">${renderReportMarkdown(content)}</div>`;
}
function reportMetric(label, value){
  return `<div class="report-metric"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}
function reportCategoryBadge(value){
  return `<span class="status ${esc(value || 'info')}">${esc(reportCategoryLabel(value))}</span>`;
}
function reportStats(content){
  const text = String(content || '');
  return {
    lines: text ? text.split(/\n/).length : 0,
    words: text.trim() ? text.trim().split(/\s+/).length : 0
  };
}
function reportHeadings(content){
  return String(content || '').split(/\n/).map(line => {
    const match = line.match(/^(#{1,4})\s+(.+)$/);
    return match ? {level: match[1].length, text: match[2].trim()} : null;
  }).filter(Boolean);
}
function reportOutline(headings){
  if(!(headings || []).length) return '<div class="empty-state">No headings</div>';
  return `<div class="report-outline">${headings.slice(0, 18).map(h => `<div class="report-outline-row" style="padding-left:${Math.max(0, h.level - 1) * 10}px">${esc(h.text)}</div>`).join('')}</div>`;
}
function renderReportMarkdown(content){
  const lines = String(content || '').split(/\n/);
  const html = [];
  let inList = false;
  let inCode = false;
  const closeList = () => { if(inList){ html.push('</ul>'); inList = false; } };
  lines.forEach(line => {
    if(line.trim().startsWith('```')){
      if(inCode){ html.push('</code></pre>'); inCode = false; }
      else { closeList(); html.push('<pre><code>'); inCode = true; }
      return;
    }
    if(inCode){
      html.push(esc(line) + '\n');
      return;
    }
    if(!line.trim()){
      closeList();
      return;
    }
    const heading = line.match(/^(#{1,4})\s+(.+)$/);
    if(heading){
      closeList();
      const level = Math.min(4, heading[1].length);
      html.push(`<h${level}>${inlineMarkdown(heading[2])}</h${level}>`);
      return;
    }
    const bullet = line.match(/^\s*[-*]\s+(.+)$/);
    if(bullet){
      if(!inList){ html.push('<ul>'); inList = true; }
      html.push(`<li>${inlineMarkdown(bullet[1])}</li>`);
      return;
    }
    closeList();
    html.push(`<p>${inlineMarkdown(line)}</p>`);
  });
  closeList();
  if(inCode) html.push('</code></pre>');
  return html.join('');
}
function inlineMarkdown(text){
  let value = esc(text);
  value = value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  value = value.replace(/`([^`]+)`/g, '<code>$1</code>');
  return value;
}
function reportCategoryLabel(value){
  return ({all:'全部',reports:'日报',daily:'日摘要',weekly:'周摘要',monthly:'月摘要',email:'邮件摘要',feedback:'反馈'})[value] || value || '报告';
}
function escText(value){ return String(value ?? ''); }
async function sources(){
  setHeader('来源','采集器、数据来源和前置条件',
    `<button class="btn primary" onclick="action('collect',{date:'today'})">采集一次</button><button class="btn" onclick="go('doctor')">诊断</button><button class="btn" onclick="sources()">刷新</button>`);
  const j=await api('/api/sources');
  const rows = j.sources || [];
  const shown = filterSourceRows(rows);
  const enabled = rows.filter(s => s.enabled).length;
  const issueRows = sourceIssues(rows);
  const totalRecords = rows.reduce((sum, source) => sum + sourceTotalCount(source), 0);
  const latest = sourceLatest(rows);
  $('subtitle').textContent = `${rows.length} 个来源 · ${enabled} 启用 · ${issueRows.length} 个问题 · ${totalRecords} 条记录`;
  $('view').innerHTML = `<div class="sources-hero">
    <div class="card">
      <div class="section-title"><h3>来源总览</h3>${status(issueRows.length ? 'warn' : 'ok')}</div>
      <div class="source-kpis">
        ${sourceKpi('来源', rows.length, `${enabled} 启用`)}
        ${sourceKpi('记录', totalRecords, 'observations')}
        ${sourceKpi('问题', issueRows.length, issueRows.length ? '需要处理' : '正常')}
        ${sourceKpi('最近', shortDateTime(latest || '-'), '最近记录')}
      </div>
      ${sourceViewFilters(rows, issueRows.length)}
    </div>
    <div class="card">
      <div class="section-title"><h3>来源动作</h3><span class="muted">采集与排查</span></div>
      <div class="source-action-grid">
        <button class="btn primary" onclick="action('collect',{date:'today'})">采集一次</button>
        <button class="btn" onclick="go('timeline')">时间线</button>
        <button class="btn" onclick="go('doctor')">诊断</button>
      </div>
    </div>
  </div>
  <div class="sources-main">
    <div>
      <div class="section-title"><h3>来源明细</h3><span class="muted">${esc(shown.length)} shown</span></div>
      <div class="source-grid">${shown.map(sourceCard).join('') || '<div class="empty-state">No sources match this filter</div>'}</div>
    </div>
    <div class="source-side">
      <div class="card">
        <div class="section-title"><h3>需要处理</h3><span class="muted">${esc(issueRows.length)} 项</span></div>
        ${sourceIssueList(issueRows)}
      </div>
      <div class="card">
        <div class="section-title"><h3>记录分布</h3><span class="muted">按记录数</span></div>
        ${sourceDistribution(rows)}
      </div>
    </div>
  </div>`;
}
function filterSourceRows(rows){
  return (rows || []).filter(source => {
    const group = sourceGroup(source.source);
    if(state.sourceView === 'all') return true;
    if(state.sourceView === 'issues') return sourceHasIssue(source);
    if(state.sourceView === 'enabled') return !!source.enabled;
    if(state.sourceView === 'disabled') return !source.enabled;
    return group === state.sourceView;
  });
}
function setSourceView(value){
  state.sourceView = value || 'all';
  sources();
}
function sourceViewFilters(rows, issueCount){
  const groupCounts = countBy(rows || [], row => sourceGroup(row.source));
  const filters = [
    ['all', '全部', (rows || []).length],
    ['issues', '需要处理', issueCount],
    ['enabled', '启用', (rows || []).filter(row => row.enabled).length],
    ['disabled', '停用', (rows || []).filter(row => !row.enabled).length],
    ['chat', '聊天', groupCounts.chat || 0],
    ['device', '设备', groupCounts.device || 0],
    ['local', '本机', groupCounts.local || 0],
    ['ai', '本地 AI', groupCounts.ai || 0],
  ];
  return `<div class="source-filters">${filters.filter(([key, , count]) => count > 0 || ['all','issues'].includes(key)).map(([key,label,count]) => `<button class="filter-pill ${state.sourceView===key?'active':''}" onclick="setSourceView('${escAttr(key)}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('')}</div>`;
}
function sourceGroup(source){
  if(['messages','apple_mail'].includes(source)) return 'chat';
  if(['mobile'].includes(source)) return 'device';
  if(['calendar','reminders','browser','filesystem'].includes(source)) return 'local';
  if(['local_ai'].includes(source)) return 'ai';
  return 'other';
}
function sourceKpi(label, value, hint){
  return `<div class="source-kpi"><div class="label">${esc(label)}</div><div class="value ${String(value ?? '').length > 10 ? 'compact' : ''}">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function sourceTotalCount(source){
  return (source.counts || []).reduce((sum, row) => sum + Number(row.count || 0), 0);
}
function sourceLatest(rows){
  const values = [];
  (rows || []).forEach(source => (source.counts || []).forEach(row => row.last && values.push(row.last)));
  values.sort();
  return values[values.length - 1] || '';
}
function sourceHasIssue(source){
  return !source.enabled || (source.notes || []).length > 0 || ((source.latest_run || {}).status && (source.latest_run || {}).status !== 'ok');
}
function sourceHealth(source){
  if(!source.enabled) return 'disabled';
  if((source.latest_run || {}).status && (source.latest_run || {}).status !== 'ok') return 'error';
  if((source.notes || []).length) return 'warn';
  return 'ok';
}
function sourceCard(source){
  const health = sourceHealth(source);
  const run = source.latest_run || {};
  return `<div class="source-card ${health === 'ok' ? '' : health === 'error' ? 'error' : health}">
    <div class="source-card-top">
      <div>
        <div class="source-name">${esc(source.source)}</div>
        <div class="item-meta">${esc(sourceGroupLabel(sourceGroup(source.source)))} · ${esc(sourceTotalCount(source))} records</div>
      </div>
      ${status(health)}
    </div>
    ${(source.notes || []).length ? `<div class="source-note-list" style="margin-top:10px">${source.notes.map(note => `<div class="source-note">${esc(note)}</div>`).join('')}</div>` : ''}
    <div class="source-run">${sourceRunSummary(source)}</div>
    ${sourceKindRows(source.counts)}
  </div>`;
}
function sourceGroupLabel(group){
  return ({chat:'聊天/通信',device:'设备同步',local:'本机采集',ai:'本地 AI',other:'其他'})[group] || group;
}
function sourceRunSummary(source){
  const run = source.latest_run || {};
  if(!run.id) return 'No collector run recorded';
  return `${run.status || '-'} · ${shortDateTime(run.started_at || '')}${run.message ? ' · ' + run.message : ''}`;
}
function sourceKindRows(counts){
  if(!(counts || []).length) return '<div class="empty-state" style="margin-top:10px">No observations yet</div>';
  return `<div class="source-kind-list">${counts.slice(0, 4).map(row => `<div class="source-kind-row"><b>${esc(row.kind)}</b><span>${esc(row.count)}</span><span>${esc(shortDateTime(row.last || ''))}</span></div>`).join('')}</div>`;
}
function sourceIssues(rows){
  return (rows || []).filter(sourceHasIssue);
}
function sourceIssueList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No source issues</div>';
  return `<div class="source-issue-list">${rows.map(source => {
    const health = sourceHealth(source);
    const run = source.latest_run || {};
    const notes = (source.notes || []).join(' · ');
    const message = notes || run.message || (!source.enabled ? 'Disabled in collectors config' : 'Needs attention');
    return `<div class="source-issue ${health === 'error' ? 'fail' : ''}"><div class="source-issue-title">${esc(source.source)} ${status(health)}</div><div class="source-issue-body">${esc(message)}</div></div>`;
  }).join('')}</div>`;
}
function sourceDistribution(rows){
  const sorted = [...(rows || [])].sort((a,b) => sourceTotalCount(b) - sourceTotalCount(a));
  return `<div class="timeline-breakdown">${sorted.map(source => `<div class="timeline-breakdown-row" onclick="setSourceView('${escAttr(sourceGroup(source.source))}')"><span>${esc(source.source)}</span><span class="queue-value">${esc(sourceTotalCount(source))}</span></div>`).join('')}</div>`;
}
async function speakerTraining(){
  const buttons = `<button class="btn primary" onclick="runSpeakerTrainingCycle()">跑一轮训练</button><button class="btn" onclick="runTrainingPayloadAction({name:'speaker_auto_organize',args:{}})">自动整理后复查</button><button class="btn" onclick="speakerTraining()">刷新</button>`;
  setHeader('Speaker 训练闭环','读取中...', buttons);
  const j = await api('/api/speaker-training');
  updateSpeakerThresholds(j.model || {});
  const summary = j.summary || {};
  const rows = filterTrainingSpeakers(j.speakers || []);
  const sampleRows = filterTrainingSamples(j.sample_queue || []);
  window.__speakerTraining = j;
  const emptyTraining = summary.training_status === 'empty';
  const trainingScoreValue = emptyTraining ? '未开始' : (summary.training_score || 0);
  const trainingScoreHint = emptyTraining ? '0 blocked' : `${summary.blocked_stages || 0} blocked`;
  $('subtitle').textContent = emptyTraining ? `未开始 · ${summary.samples || 0} samples · ${summary.missing_embeddings || 0} missing embeddings` : `${summary.training_score || 0}/100 · ${summary.needs_work_speakers || 0} need work · ${summary.missing_embeddings || 0} missing embeddings`;
  $('view').innerHTML = `
    <div class="training-hero">
      <section class="card">
        <div class="section-title"><h3>训练状态</h3><span class="muted">${esc((j.model || {}).embedding_model || '-')}</span></div>
        <div class="training-kpis">
          ${trainingKpi('训练分数', trainingScoreValue, trainingScoreHint)}
          ${trainingKpi('稳定身份', `${summary.stable_speakers || 0}/${summary.speakers || 0}`, `${summary.needs_work_speakers || 0} need work`)}
          ${trainingKpi('样本/Embedding', `${summary.samples || 0}/${summary.embeddings || 0}`, `${summary.missing_embeddings || 0} missing`)}
          ${trainingKpi('代表样本', summary.representative_samples || 0, `${summary.low_confidence_samples || 0} low confidence`)}
        </div>
        <div class="training-toolbar">${trainingViewPills(j.speakers || [], j.sample_queue || [])}</div>
      </section>
      <section class="card">
        <div class="section-title"><h3>闭环阶段</h3><span class="muted">sample -> profile</span></div>
        ${trainingStageGrid(j.stages || [])}
      </section>
    </div>
    <div class="training-main">
      <section class="card">
        <div class="section-title"><h3>Speaker 队列</h3><span class="muted">${esc(rows.length)} shown</span></div>
        ${trainingSpeakerList(rows)}
      </section>
      <aside style="display:grid;gap:14px;min-width:0">
        <section class="card">
          <div class="section-title"><h3>样本队列</h3><span class="muted">${esc(sampleRows.length)} shown</span></div>
          ${trainingSampleList(sampleRows)}
        </section>
        <section class="card">
          <div class="section-title"><h3>最近整理</h3><span class="muted">${esc((j.recent_matches || []).length)} rows</span></div>
          ${trainingMatchList(j.recent_matches || [])}
        </section>
      </aside>
    </div>`;
}
function trainingKpi(label, value, hint){
  return `<div class="training-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function trainingViewPills(speakers, samples){
  const needsWork = (speakers || []).filter(row => !['confirmed','stable','empty'].includes(row.training_state)).length;
  const filters = [
    ['needs_work', '待训练', needsWork],
    ['samples', '样本问题', (samples || []).filter(row => (row.issues || []).length).length],
    ['stable', '稳定', (speakers || []).filter(row => ['confirmed','stable'].includes(row.training_state)).length],
    ['all', '全部', (speakers || []).length],
  ];
  return filters.map(([key,label,count]) => `<button class="filter-pill ${state.speakerTrainingView===key?'active':''}" onclick="setSpeakerTrainingView('${key}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`).join('');
}
function setSpeakerTrainingView(value){
  state.speakerTrainingView = value || 'needs_work';
  speakerTraining();
}
function trainingStageGrid(stages){
  if(!(stages || []).length) return '<div class="empty-state">No training stages</div>';
  return `<div class="training-stage-grid">${stages.map(stage => `<div class="training-stage-card ${esc(stage.status || 'ok')}">
    <div class="label">${esc(stage.label || stage.key)}</div>
    <div class="training-title" style="margin-top:4px">${esc(trainingStageStatus(stage.status))}</div>
    <div class="hint">${esc(stage.detail || '')}</div>
    ${stage.action ? `<div class="training-actions"><button class="btn" data-action="${escAttr(JSON.stringify(stage.action))}" onclick="runTrainingAction(this)">${esc(stage.action.label || '执行')}</button></div>` : ''}
  </div>`).join('')}</div>`;
}
function trainingStageStatus(value){
  return ({ok:'OK', ready:'待运行', blocked:'卡住', empty:'未开始'})[value || 'ok'] || value;
}
function filterTrainingSpeakers(rows){
  const view = state.speakerTrainingView || 'needs_work';
  return (rows || []).filter(row => {
    if(view === 'stable') return ['confirmed','stable'].includes(row.training_state);
    if(view === 'all') return true;
    if(view === 'samples') return (row.issues || []).some(issue => ['missing_embedding','missing_confidence','low_confidence','missing_representative','single_sample'].includes(issue));
    return !['confirmed','stable','empty'].includes(row.training_state);
  });
}
function filterTrainingSamples(rows){
  const view = state.speakerTrainingView || 'needs_work';
  return (rows || []).filter(row => {
    const issues = row.issues || [];
    if(view === 'stable') return row.representative || !issues.length;
    if(view === 'all') return true;
    if(view === 'samples') return issues.length;
    return issues.length || row.recommended_action;
  }).slice(0, 40);
}
function trainingSpeakerList(rows){
  if(!(rows || []).length) return '<div class="empty-state">当前筛选没有需要训练的 speaker</div>';
  return `<div class="training-list">${rows.map(trainingSpeakerCard).join('')}</div>`;
}
function trainingSpeakerCard(row){
  const actionButton = row.recommended_action ? `<button class="btn primary" data-action="${escAttr(JSON.stringify(row.recommended_action))}" onclick="runTrainingAction(this)">${esc(row.recommended_action.label || '执行')}</button>` : '';
  return `<article class="training-card ${esc(row.training_state || '')}">
    <div class="training-head">
      <div>
        <div class="training-title">${esc(row.display_name || `Voice ${row.id}`)}</div>
        <div class="item-meta">ID ${esc(row.id)} · ${esc(row.sample_count || 0)} samples · ${esc(row.embedding_count || 0)} embeddings · ${esc(row.day_count || 0)} days</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${status(trainingStateLabel(row.training_state))}${status((row.confidence_summary || {}).level || 'info')}</div>
    </div>
    <div class="training-body">${esc((row.confidence_summary || {}).detail || '')}</div>
    <div class="project-keywords">${(row.issues || []).map(issue => `<span class="evidence-chip">${esc(trainingIssueLabel(issue))}</span>`).join('') || '<span class="evidence-chip">ready</span>'}</div>
    <div class="training-actions">
      ${actionButton}
      <button class="btn" onclick="openTrainingSpeaker('${escAttr(row.id)}')">打开</button>
      <button class="btn" onclick="openTrainingSpeakerSamples('${escAttr(row.id)}')">样本</button>
    </div>
  </article>`;
}
function trainingSampleList(rows){
  if(!(rows || []).length) return '<div class="empty-state">样本队列没有待处理项</div>';
  return `<div class="training-sample-list">${rows.map(trainingSampleCard).join('')}</div>`;
}
function trainingSampleCard(row){
  const actionButton = row.recommended_action ? `<button class="btn" data-action="${escAttr(JSON.stringify(row.recommended_action))}" onclick="runTrainingAction(this)">${esc(row.recommended_action.label || '执行')}</button>` : '';
  return `<div class="speaker-sample-card ${esc(trainingSampleCardClass(row))}">
    <div class="speaker-match-row"><div><b>${esc(row.speaker_name || row.speaker_id)}</b><div class="item-meta">sample ${esc(row.id || '-')} · ${esc(formatSecondsRange(row.start_seconds, row.end_seconds))} · ${esc(trainingSampleConfidence(row))}</div></div>${status(row.representative ? '代表' : 'sample')}</div>
    <div class="speaker-sample-tags">${(row.issues || []).map(issue => `<span class="evidence-chip">${esc(trainingIssueLabel(issue))}</span>`).join('') || '<span class="evidence-chip">ready</span>'}</div>
    <div class="speaker-transcript">${esc(row.transcript || '')}</div>
    ${row.sample_path ? `<audio controls preload="none"><source src="/api/speaker-sample/${escAttr(row.id)}" type="audio/mp4"></audio>` : ''}
    <div class="training-actions">${actionButton}<button class="btn" onclick="splitSpeakerSample('${escAttr(row.id)}')">手动切分样本</button><button class="btn" onclick="openTrainingSpeakerSamples('${escAttr(row.speaker_id)}')">查看相关</button></div>
  </div>`;
}
function trainingSampleCardClass(row){
  const issues = row.issues || [];
  if(issues.includes('low_confidence')) return 'low-confidence';
  if(issues.includes('missing_embedding')) return 'missing-embedding';
  if(row.representative) return 'representative';
  return 'ok';
}
function trainingSampleConfidence(row){
  const n = Number(row.sample_confidence);
  return Number.isFinite(n) ? `sample ${formatPercent(n)}` : 'unscored';
}
function trainingMatchList(rows){
  if(!(rows || []).length) return '<div class="empty-state">暂无整理记录</div>';
  return `<div class="training-match-list">${rows.slice(0, 8).map(match => `<div class="speaker-match-card">
    <div class="speaker-match-row"><div><b>${esc(match.source_name || match.source_speaker_id)}</b><div class="item-meta">to ${esc(match.target_name || match.target_speaker_id || '-')} · ${esc(shortDateTime(match.created_at || ''))}</div></div>${status(match.status || 'info')}</div>
    <div class="speaker-meta"><span>score ${esc(formatScore(match.score))}</span><span>threshold ${esc(formatScore(match.threshold))}</span></div>
  </div>`).join('')}</div>`;
}
function trainingStateLabel(value){
  return ({confirmed:'已确认', stable:'稳定', missing_embedding:'缺 embedding', needs_scoring:'待评分', low_confidence:'低一致性', review_needed:'待确认', pending_auto:'自动整理待确认', hidden:'隐藏', empty:'空'})[value || ''] || value || 'info';
}
function trainingIssueLabel(value){
  return ({no_samples:'无样本', single_sample:'单样本', missing_embedding:'缺 embedding', missing_confidence:'未评分', low_confidence:'低一致性', missing_representative:'缺代表样本', auto_name:'自动名', no_audio:'缺音频'})[value || ''] || value;
}
async function runTrainingAction(button){
  const payload = JSON.parse(button.dataset.action || '{}');
  await runTrainingPayloadAction(payload);
}
async function runTrainingPayloadAction(payload){
  if(!payload.name) return;
  if(payload.name === 'speaker_auto_organize' && !askConfirm(`执行自动整理会按当前配置阈值 ${formatScore(speakerAutoMergeThreshold())} 合并相似未命名 Voice；命名说话人只进入人工候选，并隐藏低相似未命名 Voice，继续？`)) return;
  await action(payload.name, payload.args || {});
}
async function runSpeakerTrainingCycle(){
  if(!askConfirm('跑一轮训练会补齐缺失 embedding、重算样本一致性并刷新代表样本；不会自动合并。继续？')) return;
  const steps = [
    {name:'speaker_repair_embeddings', args:{apply:true}, label:'补 embedding'},
    {name:'speaker_refresh_sample_confidence', args:{}, label:'重算一致性'},
    {name:'speaker_refresh_representatives', args:{per_speaker:3}, label:'刷新代表样本'},
  ];
  const lines = [];
  for(const step of steps){
    const j = await api('/api/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:step.name,args:step.args})});
    lines.push(`${j.ok?'OK':'FAILED'} ${step.label}\n${j.stdout || j.stderr || ''}`);
    if(!j.ok) break;
  }
  toast(lines.join('\n---\n'));
  speakerTraining();
}
function openTrainingSpeaker(id){
  state.speakerSelectedIds = id ? [String(id)] : [];
  state.speakerView = 'all';
  go('speakers');
}
function openTrainingSpeakerSamples(id){
  state.speakerSelectedIds = id ? [String(id)] : [];
  state.speakerSamplesFor = id ? 'selected' : 'visible';
  state.speakerSampleView = 'all';
  state.speakerContextSource = id ? 'selection' : 'idle';
  go('speakers');
}
async function speakers(){
  setHeader('说话人','自动整理、人工确认、样本快速筛选', `<button class="btn primary" onclick="speakers()">刷新</button>`);
  const [j, quality] = await Promise.all([api('/api/speakers'), api('/api/speaker-quality?view=needs_work')]);
  const thresholds = updateSpeakerThresholds(((j.config || {}).speaker_recognition || j.config || {}));
  const speakerRows = j.speakers || [];
  const sampleRows = j.samples || [];
  const matchRows = j.matches || [];
  const profiles = j.profiles || [];
  state.speakers = speakerRows;
  state.speakerSamples = sampleRows;
  state.speakerProfiles = profiles;
  const shownSpeakers = sortSpeakers(filterSpeakers(speakerRows));
  state.speakerShownIds = shownSpeakers.map(s => String(s.id));
  state.speakerSelectedIds = speakerSelectedIds().filter(id => speakerRows.some(s => String(s.id) === String(id)));
  const selectedSet = new Set(state.speakerSelectedIds.map(String));
  const selectedRows = speakerRows.filter(s => selectedSet.has(String(s.id)));
  if(state.speakerBulkTarget && !speakerRows.some(s => String(s.id) === String(state.speakerBulkTarget))) state.speakerBulkTarget = '';
  const shownSet = new Set(state.speakerShownIds);
  const scopedSamples = speakerSampleScopeRows(sampleRows, selectedSet, shownSet);
  const focusedSamples = sortSpeakerSamples(filterSpeakerSamples(scopedSamples));
  state.speakerFocusedSampleSpeakerIds = [...new Set(focusedSamples.map(row => String(row.speaker_id || '')).filter(Boolean))];
  state.speakerFocusedSampleIds = focusedSamples.map(row => String(row.id || '')).filter(Boolean);
  const sampleFilterCounts = speakerSampleFilterCounts(scopedSamples);
  const provisional = speakerRows.filter(s => String(s.identity_status || '') === 'provisional').length;
  const noSamples = speakerRows.filter(s => Number(s.sample_count || 0) <= 0).length;
  const lowConfidence = speakerRows.filter(s => speakerHasLowConfidence(s)).length;
  const pendingAuto = speakerRows.filter(speakerIsAutoPending).length;
  const hidden = speakerRows.filter(speakerIsHidden).length;
  const missingEmbeddings = sampleRows.filter(sampleMissingEmbedding).length;
  const representativeSamples = sampleRows.filter(sampleIsRepresentative).length;
  const activeRows = speakerRows.filter(s => !speakerIsHidden(s));
  const confirmed = speakerRows.filter(s => speakerReviewStatus(s) === 'confirmed').length;
  const totalSamples = speakerRows.reduce((sum, s) => sum + Number(s.sample_count || 0), 0);
  const avgConfidence = activeRows.length ? Math.round((activeRows.reduce((sum, s) => sum + Number(s.confidence || 0), 0) / activeRows.length) * 100) : 0;
  $('subtitle').textContent = `${activeRows.length} 活跃 · ${pendingAuto} 自动整理待确认 · ${hidden} 已隐藏 · ${totalSamples} 样本 · 自动整理阈值 ${formatScore(thresholds.auto_merge_threshold)}`;
  $('view').innerHTML = `<div class="speakers-main">
    <div class="speaker-content">
      <div class="card speaker-workbench">
        <div class="speaker-command-row">
          <div class="speaker-command-copy">
            <div class="section-title"><h3>整理队列</h3>${speakerStatusBadge(pendingAuto ? 'auto_merged_pending_review' : hidden ? 'low_similarity_hidden' : 'ok')}</div>
            <p class="speaker-command-note">先用队列筛说话人；点卡片后下方样本会立刻切到选中说话人。批量确认、恢复和重算在右侧一次完成。</p>
          </div>
        </div>
        <div class="speaker-kpis">
          ${speakerKpi('活跃说话人', activeRows.length, `${confirmed} 已确认`)}
          ${speakerKpi('自动整理待确认', pendingAuto, '合并后需确认')}
          ${speakerKpi('隐藏低相似', hidden, '默认不再打扰')}
          ${speakerKpi('自动整理阈值', formatScore(thresholds.auto_merge_threshold), `低一致性 ${formatScore(thresholds.candidate_threshold)}`)}
          ${speakerKpi('缺 embedding', missingEmbeddings, '样本无法匹配')}
          ${speakerKpi('代表样本', representativeSamples, '人物档案锚点')}
        </div>
      </div>
      <div class="speaker-review-layout">
        <section class="speaker-panel">
          <div class="speaker-panel-head">
            <div><h3>${esc(speakerViewLabel(state.speakerView))}</h3><div class="item-meta">${esc(shownSpeakers.length)} / ${esc(speakerRows.length)} 显示 · ${esc(selectedRows.length)} 已选</div></div>
            <span class="muted">点击卡片选择</span>
          </div>
          <div class="speaker-filter-row">
            <div class="speaker-filter-label">队列</div>
            <div class="speaker-filters">
              ${speakerFilter('active','活跃',activeRows.length)}
              ${speakerFilter('pending_auto','整理待确认',pendingAuto)}
              ${speakerFilter('low_confidence','低一致性',lowConfidence)}
              ${speakerFilter('review','人工复查',speakerRows.filter(s => !speakerIsHidden(s) && speakerNeedsReview(s)).length)}
              ${speakerFilter('hidden','隐藏',hidden)}
              ${speakerFilter('all','全部',speakerRows.length)}
            </div>
          </div>
          <div class="speaker-review-toolbar">
            <input id="speakerQ" value="${escAttr(state.speakerQ)}" placeholder="搜索 ID、名字、状态、来源、一致性" onkeydown="speakerSearchKey(event)" aria-label="speaker search">
            <select id="speakerSort" onchange="setSpeakerSort(this.value)">${speakerSortOptions()}</select>
            <button class="btn primary" onclick="applySpeakerSearch()">筛选</button>
          </div>
          <div class="speaker-grid">${shownSpeakers.map(speakerCard).join('') || '<div class="empty-state">No speakers match this filter</div>'}</div>
        </section>
        <section class="speaker-panel speaker-sample-panel">
          <div class="speaker-panel-head">
            <div>
              <h3>样本浏览</h3>
              <div class="speaker-sample-summary"><span>${esc(speakerSampleScopeLabel(selectedRows, shownSpeakers))}</span><span>${esc(focusedSamples.length)} / ${esc(scopedSamples.length)} 显示</span></div>
            </div>
            <span class="muted">${esc(sampleRows.length)} total</span>
          </div>
          <div class="speaker-sample-filters">
            ${speakerSampleFilter('all','全部',sampleFilterCounts.all)}
            ${speakerSampleFilter('needs_work','需处理',sampleFilterCounts.needs_work)}
            ${speakerSampleFilter('low_confidence','低一致性',sampleFilterCounts.low_confidence)}
            ${speakerSampleFilter('missing_embedding','缺 embedding',sampleFilterCounts.missing_embedding)}
            ${speakerSampleFilter('representative','代表',sampleFilterCounts.representative)}
            ${speakerSampleFilter('playable','可播放',sampleFilterCounts.playable)}
            ${speakerSampleFilter('detached','已分离',sampleFilterCounts.detached)}
          </div>
          <div class="speaker-sample-toolbar">
            <input id="speakerSampleQ" value="${escAttr(state.speakerSampleQ)}" placeholder="搜样本：说话人、obs、转写、状态" onkeydown="speakerSampleSearchKey(event)" aria-label="speaker sample search">
            <select id="speakerSamplesFor" onchange="setSpeakerSamplesFor(this.value)">${speakerSampleScopeOptions()}</select>
            <select id="speakerSampleSort" onchange="setSpeakerSampleSort(this.value)">${speakerSampleSortOptions()}</select>
            <button class="btn primary" onclick="applySpeakerSampleSearch()">筛选</button>
          </div>
          <div class="speaker-sample-list expanded">${speakerSampleList(focusedSamples, {limit: 40, expanded: true})}</div>
        </section>
      </div>
    </div>
    <div class="speaker-side">
      ${speakerOperationPanel(speakerRows, selectedRows)}
      <div class="card">
        <div class="section-title"><h3>质量中心</h3><span class="muted">${esc((quality.summary || {}).needs_work || 0)} need work</span></div>
        ${qualityList(quality.speakers || [])}
      </div>
      ${speakerProfilePanel(selectedRows, profiles)}
      <details class="card compact-details">
        <summary>近期匹配记录 ${esc(matchRows.length)} 条</summary>
        <div class="compact-details-body">${speakerMatchList(matchRows)}</div>
      </details>
    </div>
  </div>`;
}
function applySpeakerSearch(){
  state.speakerQ = $('speakerQ').value;
  state.speakerContextSource = String(state.speakerQ || '').trim() ? 'queue' : 'idle';
  speakers();
}
function speakerSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applySpeakerSearch();
  }
}
function setSpeakerView(value){
  state.speakerView = value || 'all';
  state.speakerContextSource = state.speakerView === 'active' && !String(state.speakerQ || '').trim() ? 'idle' : 'queue';
  speakers();
}
function setSpeakerSort(value){
  state.speakerSort = value || 'review';
  speakers();
}
function setSpeakerSamplesFor(value){
  state.speakerSamplesFor = value || 'visible';
  state.speakerContextSource = state.speakerSamplesFor === 'visible' && state.speakerSampleView === 'all' && !String(state.speakerSampleQ || '').trim() ? 'idle' : 'samples';
  speakers();
}
function setSpeakerSampleView(value){
  state.speakerSampleView = value || 'all';
  state.speakerContextSource = state.speakerSampleView === 'all' && state.speakerSamplesFor === 'visible' && !String(state.speakerSampleQ || '').trim() ? 'idle' : 'samples';
  speakers();
}
function setSpeakerSampleSort(value){
  state.speakerSampleSort = value || 'needs_work';
  speakers();
}
function applySpeakerSampleSearch(){
  state.speakerSampleQ = $('speakerSampleQ').value;
  state.speakerContextSource = String(state.speakerSampleQ || '').trim() || state.speakerSampleView !== 'all' || state.speakerSamplesFor !== 'visible' ? 'samples' : 'idle';
  speakers();
}
function speakerSampleSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applySpeakerSampleSearch();
  }
}
function filterSpeakers(rows){
  const q = String(state.speakerQ || '').trim().toLowerCase();
  return (rows || []).filter(s => {
    if(state.speakerView !== 'hidden' && state.speakerView !== 'all' && speakerIsHidden(s)) return false;
    if(state.speakerView === 'active' && speakerIsHidden(s)) return false;
    if(state.speakerView === 'pending_auto' && !speakerIsAutoPending(s)) return false;
    if(state.speakerView === 'review' && (speakerIsHidden(s) || !speakerNeedsReview(s))) return false;
    if(state.speakerView === 'provisional' && String(s.identity_status || '') !== 'provisional') return false;
    if(state.speakerView === 'low_confidence' && (speakerIsHidden(s) || !speakerHasLowConfidence(s))) return false;
    if(state.speakerView === 'samples' && Number(s.sample_count || 0) <= 0) return false;
    if(state.speakerView === 'empty' && Number(s.sample_count || 0) > 0) return false;
    if(state.speakerView === 'named' && speakerNeedsReview(s)) return false;
    if(state.speakerView === 'hidden' && !speakerIsHidden(s)) return false;
    if(!q) return true;
    const evidence = s.evidence || {};
    const metadata = s.metadata || {};
    const sourceNames = (metadata.auto_merge_sources || []).map(item => `${item.source_display_name || ''} ${item.source_speaker_id || ''}`).join(' ');
    const haystack = [s.id, s.display_name, s.identity_status, speakerReviewStatus(s), sourceNames, s.confidence, s.sample_count, s.alias_count, evidence.day_count, evidence.latest_seen_at].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function sortSpeakers(rows){
  const list = [...(rows || [])];
  const reviewScore = s => (speakerIsAutoPending(s) ? 2000 : 0) + (speakerNeedsReview(s) ? 1000 : 0) + (Number(s.sample_count || 0) <= 0 ? 200 : 0) + (speakerHasLowConfidence(s) ? 100 : 0);
  const latestTs = s => Date.parse(speakerVisibleTime(s) || '') || 0;
  const confidence = s => Number.isFinite(Number(s.confidence)) ? Number(s.confidence) : -1;
  if(state.speakerSort === 'samples') list.sort((a,b) => Number(b.sample_count || 0) - Number(a.sample_count || 0) || Number(a.id) - Number(b.id));
  else if(state.speakerSort === 'confidence') list.sort((a,b) => confidence(b) - confidence(a) || Number(a.id) - Number(b.id));
  else if(state.speakerSort === 'recent') list.sort((a,b) => latestTs(b) - latestTs(a) || Number(a.id) - Number(b.id));
  else if(state.speakerSort === 'id') list.sort((a,b) => Number(a.id) - Number(b.id));
  else list.sort((a,b) => reviewScore(b) - reviewScore(a) || latestTs(b) - latestTs(a) || Number(a.id) - Number(b.id));
  return list;
}
function speakerNeedsReview(s){
  const name = String(s.display_name || '');
  if(speakerIsAutoPending(s)) return true;
  if(speakerReviewStatus(s) === 'confirmed') return false;
  return String(s.identity_status || '') === 'provisional' || /^speaker\s*\d+$/i.test(name) || /^\d+$/.test(name) || Number(s.sample_count || 0) <= 0;
}
function speakerHasLowConfidence(s){
  if(speakerReviewStatus(s) === 'confirmed') return false;
  const confidence = Number(s.confidence);
  return Number.isFinite(confidence) && confidence > 0 && confidence < speakerLowConfidenceThreshold();
}
function sampleConfidenceValue(sample){
  const n = Number((sample.metadata || {}).sample_confidence);
  return Number.isFinite(n) ? n : null;
}
function sampleHasLowConfidence(sample){
  const confidence = sampleConfidenceValue(sample);
  return confidence !== null && confidence > 0 && confidence < speakerLowConfidenceThreshold();
}
function sampleHasError(sample){
  const metadata = sample.metadata || {};
  const statusText = String(metadata.status || '').toLowerCase();
  return !!metadata.error || ['error','fail','failed'].includes(statusText);
}
function sampleMissingEmbedding(sample){
  const metadata = sample.metadata || {};
  return !metadata.sample_confidence_model && !metadata.embedding_model && metadata.embedding_repair_status !== 'ok';
}
function sampleIsRepresentative(sample){
  return (sample.metadata || {}).representative_sample === true;
}
function sampleIsDetached(sample){
  return String((sample.metadata || {}).sample_role || '').includes('detached');
}
function speakerConfidenceSummary(s){
  return s.confidence_summary || {label: formatPercent(s.confidence), level: 'unknown', detail: ''};
}
function speakerConfidenceText(s){
  const summary = speakerConfidenceSummary(s);
  if(summary.value == null || summary.level === 'insufficient_evidence' || summary.level === 'missing_embedding' || summary.level === 'no_samples'){
    return summary.label || '-';
  }
  return `${summary.label || ''} ${formatPercent(summary.value)}`.trim();
}
function speakerReviewStatus(s){
  return String((s.metadata || {}).speaker_review_status || '');
}
function speakerIsAutoPending(s){
  return speakerReviewStatus(s) === 'auto_merged_pending_review';
}
function speakerIsHidden(s){
  const metadata = s.metadata || {};
  return metadata.speaker_hidden === true || speakerReviewStatus(s) === 'low_similarity_hidden';
}
function speakerViewLabel(value){
  return ({active:'活跃说话人', pending_auto:'自动整理待确认', review:'人工复查', low_confidence:'低一致性说话人', hidden:'隐藏低相似 Voice', all:'全部说话人'})[value || 'active'] || '说话人列表';
}
function speakerVisibleTime(s){
  const evidence = s.evidence || {};
  return evidence.latest_seen_at || s.latest_sample_at || s.created_at || '';
}
function sortSpeakerSamples(rows){
  const list = [...(rows || [])];
  const sampleConfidence = sample => sampleConfidenceValue(sample);
  const created = sample => Date.parse(sample.created_at || '') || 0;
  const duration = sample => Math.max(0, Number(sample.end_seconds || 0) - Number(sample.start_seconds || 0));
  const reviewScore = sample => (sampleMissingEmbedding(sample) ? 3000 : 0) + (sampleHasLowConfidence(sample) ? 2000 : 0) + (sampleHasError(sample) ? 1000 : 0);
  if(state.speakerSampleSort === 'recent') return list.sort((a,b) => created(b) - created(a) || Number(b.id || 0) - Number(a.id || 0));
  if(state.speakerSampleSort === 'speaker') return list.sort((a,b) => String(a.speaker_name || a.speaker_id || '').localeCompare(String(b.speaker_name || b.speaker_id || '')) || Number(a.id || 0) - Number(b.id || 0));
  if(state.speakerSampleSort === 'duration') return list.sort((a,b) => duration(b) - duration(a) || Number(b.id || 0) - Number(a.id || 0));
  return list.sort((a,b) => {
    const ar = reviewScore(a);
    const br = reviewScore(b);
    if(ar !== br) return br - ar;
    const av = sampleConfidence(a);
    const bv = sampleConfidence(b);
    const afin = Number.isFinite(av);
    const bfin = Number.isFinite(bv);
    if(afin && bfin && av !== bv) return av - bv;
    if(afin !== bfin) return afin ? -1 : 1;
    return Number(b.id || 0) - Number(a.id || 0);
  });
}
function speakerSampleScopeRows(rows, selectedSet, shownSet){
  const scope = state.speakerSamplesFor || 'visible';
  if(scope === 'selected') return selectedSet.size ? (rows || []).filter(row => selectedSet.has(String(row.speaker_id || ''))) : [];
  if(scope === 'all') return rows || [];
  return shownSet.size ? (rows || []).filter(row => shownSet.has(String(row.speaker_id || ''))) : [];
}
function filterSpeakerSamples(rows){
  const q = String(state.speakerSampleQ || '').trim().toLowerCase();
  return (rows || []).filter(sample => {
    if(state.speakerSampleView === 'needs_work' && !(sampleHasLowConfidence(sample) || sampleMissingEmbedding(sample) || sampleHasError(sample))) return false;
    if(state.speakerSampleView === 'low_confidence' && !sampleHasLowConfidence(sample)) return false;
    if(state.speakerSampleView === 'missing_embedding' && !sampleMissingEmbedding(sample)) return false;
    if(state.speakerSampleView === 'representative' && !sampleIsRepresentative(sample)) return false;
    if(state.speakerSampleView === 'playable' && !sample.sample_path) return false;
    if(state.speakerSampleView === 'detached' && !sampleIsDetached(sample)) return false;
    if(!q) return true;
    const metadata = sample.metadata || {};
    const haystack = [
      sample.id,
      sample.speaker_id,
      sample.speaker_name,
      sample.observation_id,
      sample.source_key,
      sample.transcript,
      sample.created_at,
      metadata.status,
      metadata.error,
      metadata.local_label,
      metadata.sample_role,
      metadata.sample_confidence,
      metadata.embedding_repair_status,
    ].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function speakerSampleFilterCounts(rows){
  const list = rows || [];
  return {
    all: list.length,
    needs_work: list.filter(sample => sampleHasLowConfidence(sample) || sampleMissingEmbedding(sample) || sampleHasError(sample)).length,
    low_confidence: list.filter(sampleHasLowConfidence).length,
    missing_embedding: list.filter(sampleMissingEmbedding).length,
    representative: list.filter(sampleIsRepresentative).length,
    playable: list.filter(sample => !!sample.sample_path).length,
    detached: list.filter(sampleIsDetached).length,
  };
}
function speakerFilter(key, label, count){
  return `<button class="filter-pill ${state.speakerView===key?'active':''}" onclick="setSpeakerView('${escAttr(key)}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`;
}
function speakerSampleFilter(key, label, count){
  return `<button class="filter-pill ${state.speakerSampleView===key?'active':''}" onclick="setSpeakerSampleView('${escAttr(key)}')">${esc(label)} <span class="chip-count">${esc(count)}</span></button>`;
}
function speakerSortOptions(){
  const options = [['review','优先待清洗'], ['recent','最近出现'], ['samples','样本最多'], ['confidence','一致性最高'], ['id','ID 顺序']];
  return options.map(([value,label]) => `<option value="${escAttr(value)}" ${state.speakerSort===value?'selected':''}>${esc(label)}</option>`).join('');
}
function speakerSampleScopeOptions(){
  const options = [['visible','当前队列样本'], ['selected','选中说话人样本'], ['all','全部样本']];
  return options.map(([value,label]) => `<option value="${escAttr(value)}" ${state.speakerSamplesFor===value?'selected':''}>${esc(label)}</option>`).join('');
}
function speakerSampleSortOptions(){
  const options = [['needs_work','问题优先'], ['recent','最新样本'], ['speaker','按说话人'], ['duration','时长最长']];
  return options.map(([value,label]) => `<option value="${escAttr(value)}" ${state.speakerSampleSort===value?'selected':''}>${esc(label)}</option>`).join('');
}
function speakerSampleScopeLabel(selectedRows, shownRows){
  if(state.speakerSamplesFor === 'selected') return selectedRows.length ? `选中 ${selectedRows.length} 个说话人` : '未选择说话人';
  if(state.speakerSamplesFor === 'all') return '全部样本';
  return `当前队列 ${shownRows.length} 个说话人`;
}
function speakerKpi(label, value, hint){
  return `<div class="speaker-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function speakerStatusBadge(value){
  const key = String(value || 'info');
  const label = ({provisional:'待确认',ok:'正常',confirmed:'已确认',accepted:'已接受',below_threshold:'低一致性',auto_merged_pending_review:'整理待确认',low_similarity_hidden:'已隐藏',needs_review:'待复查',info:'info'})[key] || key;
  return `<span class="status ${esc(key)}">${esc(label)}</span>`;
}
function speakerOperationPanel(rows, selectedRows){
  const selectedCount = selectedRows.length;
  const selectedSamples = selectedRows.reduce((sum, row) => sum + Number(row.sample_count || 0), 0);
  const single = selectedRows.length === 1 ? selectedRows[0] : null;
  const renameId = single ? String(single.id) : '';
  const renameName = single ? String(single.display_name || '') : '';
  const mergeTarget = state.speakerBulkTarget || preferredSpeakerMergeTarget(selectedRows);
  const visibleRows = visibleSpeakerRows(rows);
  const context = speakerContextState(selectedRows, visibleRows);
  return `<div class="card speaker-context-card">
    <div class="section-title"><h3>下一步</h3><span class="muted">${esc(context.badge)}</span></div>
    <div class="speaker-tools">
      ${speakerContextSummary(context, selectedCount, selectedSamples, mergeTarget, rows)}
      ${speakerContextActions(context)}
      ${selectedCount >= 2 ? `<div class="speaker-action-group">
        <div class="speaker-action-title">合并选中</div>
        <div class="speaker-bulk-row">
          <select id="bulkMergeTarget" onchange="state.speakerBulkTarget=this.value; speakers()">${speakerBulkTargetOptions(rows, mergeTarget)}</select>
          <button class="btn primary" onclick="bulkMergeSpeakers()">合并</button>
        </div>
      </div>` : ''}
      ${single ? `<div class="speaker-action-group">
        <div class="speaker-action-title">重命名</div>
        <div class="speaker-tool-row">
          <select id="renameId" onchange="selectSpeakerForRename(this.value)">${speakerSelectOptions(rows, renameId, '选择说话人')}</select>
          <input id="renameName" value="${escAttr(renameName)}" placeholder="显示名">
          <button class="btn primary" onclick="renameSelectedSpeaker()">保存</button>
        </div>
      </div>` : ''}
      <details class="compact-details">
        <summary>维护工具</summary>
        <div class="compact-details-body">
          <button class="btn" onclick="autoOrganizeSpeakers()">自动整理相似声音</button>
          <button class="btn" onclick="refreshSpeakerSampleConfidence()">重算全部一致性</button>
          <button class="btn" onclick="repairSpeakerEmbeddings()">补 embedding</button>
          <button class="btn" onclick="refreshRepresentativeSamples()">刷新代表样本</button>
          <button class="btn" onclick="reviveHiddenSpeakers()">复活隐藏队列</button>
          <button class="btn" onclick="action('speaker_normalize_names',{})">整理自动名</button>
          <button class="btn" onclick="action('analyze_audio',{limit:5})">分析 5 条音频</button>
        </div>
      </details>
      ${selectedCount ? `<details class="compact-details speaker-danger-row">
        <summary>危险操作</summary>
        <div class="compact-details-body">
          <button class="btn danger" onclick="bulkDeleteSpeakers()">删除选中</button>
        </div>
      </details>` : ''}
    </div>
  </div>`;
}
function visibleSpeakerRows(rows){
  const ids = new Set(visibleSpeakerIds());
  return (rows || []).filter(row => ids.has(String(row.id)));
}
function speakerContextState(selectedRows, visibleRows){
  const selectedCount = selectedRows.length;
  const sampleContext = state.speakerSampleView !== 'all' || !!String(state.speakerSampleQ || '').trim() || state.speakerSamplesFor !== 'visible';
  const queueContext = state.speakerView !== 'active' || !!String(state.speakerQ || '').trim();
  if(selectedCount){
    return {
      type: 'selection',
      title: selectedCount === 1 ? selectedRows[0].display_name || `Speaker ${selectedRows[0].id}` : `${selectedCount} 个说话人`,
      note: selectedCount === 1 ? '正在查看这个说话人的样本和可用动作。' : '多选后只显示批量相关动作。',
      badge: `${selectedCount} 已选`,
      rows: selectedRows,
    };
  }
  if(state.speakerContextSource === 'queue' && queueContext){
    return {
      type: 'queue',
      title: speakerViewLabel(state.speakerView),
      note: '当前队列筛选后，只显示适合这批说话人的动作。',
      badge: `${visibleRows.length} in queue`,
      rows: visibleRows,
    };
  }
  if(state.speakerContextSource === 'samples' && sampleContext){
    return {
      type: 'samples',
      title: speakerSampleContextLabel(),
      note: '当前 sample 筛选会决定这里显示哪些修复或聚类动作。',
      badge: `${focusedSampleSpeakerIds().length} 个说话人`,
      rows: visibleRows,
    };
  }
  if(queueContext){
    return {
      type: 'queue',
      title: speakerViewLabel(state.speakerView),
      note: '当前队列筛选后，只显示适合这批说话人的动作。',
      badge: `${visibleRows.length} in queue`,
      rows: visibleRows,
    };
  }
  return {
    type: 'idle',
    title: '选择一个说话人或筛选队列',
    note: '这里会自动出现和当前上下文相关的按钮，其它按钮保持隐藏。',
    badge: '待选择',
    rows: visibleRows,
  };
}
function speakerFallbackContextSource(){
  if(state.speakerView !== 'active' || String(state.speakerQ || '').trim()) return 'queue';
  if(state.speakerSampleView !== 'all' || state.speakerSamplesFor !== 'visible' || String(state.speakerSampleQ || '').trim()) return 'samples';
  return 'idle';
}
function speakerContextSummary(context, selectedCount, selectedSamples, mergeTarget, rows){
  const chips = [];
  if(context.type === 'selection'){
    chips.push(speakerSelectionChip('已选说话人', `${selectedCount} 个`));
    chips.push(speakerSelectionChip('样本记录', `${selectedSamples} 个`));
    if(selectedCount >= 2) chips.push(speakerSelectionChip('合并到', mergeTarget ? speakerCompactLabel(speakerById(rows, mergeTarget)) : '默认第一个已选'));
  } else if(context.type === 'queue'){
    chips.push(speakerSelectionChip('当前队列', speakerViewLabel(state.speakerView)));
    chips.push(speakerSelectionChip('显示说话人', `${context.rows.length} 个`));
  } else if(context.type === 'samples'){
    chips.push(speakerSelectionChip('样本筛选', speakerSampleContextLabel()));
    chips.push(speakerSelectionChip('涉及说话人', `${focusedSampleSpeakerIds().length} 个`));
  }
  const chipGrid = chips.length ? `<div class="speaker-selection-grid">${chips.join('')}</div>` : '';
  return `<div class="speaker-context-summary">
    <div class="speaker-context-title">${esc(context.title)}</div>
    <div class="speaker-context-note">${esc(context.note)}</div>
    ${chipGrid}
  </div>`;
}
function speakerContextActions(context){
  const buttons = speakerContextButtons(context);
  if(!buttons.length) return '<div class="empty-state">点击一个说话人、队列筛选或 sample 筛选后，相关按钮会自动出现。</div>';
  return `<div class="speaker-context-actions">${buttons.join('')}</div>`;
}
function speakerContextButtons(context){
  const buttons = [];
  if(context.type === 'selection'){
    const rows = context.rows || [];
    const hasHidden = rows.some(speakerIsHidden);
    const hasVisible = rows.some(row => !speakerIsHidden(row));
    if(hasVisible) buttons.push('<button class="btn primary" onclick="confirmSelectedSpeakers()">确认选中</button>');
    if(hasHidden) buttons.push('<button class="btn primary" onclick="unhideSelectedSpeakers()">取消隐藏</button>');
    buttons.push('<button class="btn" onclick="refreshSelectedSpeakerSampleConfidence()">重算选中一致性</button>');
    buttons.push('<button class="btn" onclick="clearSpeakerSelection()">清空选择</button>');
    return buttons;
  }
  if(context.type === 'queue'){
    const count = (context.rows || []).length;
    if(!count) return buttons;
    if(state.speakerView === 'pending_auto' || state.speakerView === 'review') buttons.push('<button class="btn primary" onclick="confirmVisibleSpeakers()">确认当前队列</button>');
    if(state.speakerView === 'hidden') buttons.push('<button class="btn primary" onclick="unhideVisibleSpeakers()">取消隐藏当前队列</button>');
    if(state.speakerView === 'low_confidence' || state.speakerView === 'review' || state.speakerQ) buttons.push('<button class="btn" onclick="refreshVisibleSpeakerSampleConfidence()">重算当前队列</button>');
    buttons.push('<button class="btn" onclick="selectVisibleSpeakers()">选择当前队列</button>');
    return buttons;
  }
  if(context.type === 'samples'){
    const ids = focusedSampleSpeakerIds();
    if(!ids.length) return buttons;
    if(state.speakerSampleView === 'missing_embedding') buttons.push('<button class="btn primary" onclick="repairSpeakerEmbeddings()">补 embedding</button>');
    if(state.speakerSampleView === 'representative') buttons.push('<button class="btn primary" onclick="refreshFocusedRepresentativeSamples()">刷新这些代表样本</button>');
    if(state.speakerSampleView === 'low_confidence' || state.speakerSampleView === 'needs_work' || state.speakerSampleQ) buttons.push('<button class="btn primary" onclick="refreshFocusedSampleSpeakerConfidence()">重算相关说话人</button>');
    buttons.push('<button class="btn" onclick="repairFocusedSampleClips()">重裁这些样本</button>');
    buttons.push('<button class="btn" onclick="selectFocusedSampleSpeakers()">选择这些样本所属说话人</button>');
    return buttons;
  }
  return buttons;
}
function speakerSampleContextLabel(){
  const viewLabel = ({all:'全部样本', needs_work:'需处理样本', low_confidence:'低一致性样本', missing_embedding:'缺 embedding 样本', representative:'代表样本', playable:'可播放样本', detached:'已分离样本'})[state.speakerSampleView || 'all'] || state.speakerSampleView || '样本';
  const scopeLabel = ({visible:'当前队列', selected:'选中说话人', all:'全部说话人'})[state.speakerSamplesFor || 'visible'] || '当前队列';
  const q = String(state.speakerSampleQ || '').trim();
  return q ? `${scopeLabel} · ${viewLabel} · "${q}"` : `${scopeLabel} · ${viewLabel}`;
}
function speakerSelectionChip(label, value='-'){
  return `<div class="speaker-selection-chip"><div class="label">${esc(label)}</div><div class="value">${esc(value || '-')}</div></div>`;
}
function speakerSelectOptions(rows, selected, placeholder){
  const head = `<option value="">${esc(placeholder || '选择说话人')}</option>`;
  return head + (rows || []).map(row => `<option value="${escAttr(row.id)}" ${String(selected || '')===String(row.id)?'selected':''}>${esc(speakerCompactLabel(row))}</option>`).join('');
}
function speakerBulkTargetOptions(rows, selected){
  const head = `<option value="">默认第一个已选</option>`;
  return head + (rows || []).map(row => `<option value="${escAttr(row.id)}" ${String(selected || '')===String(row.id)?'selected':''}>${esc(speakerCompactLabel(row))}</option>`).join('');
}
function speakerCompactLabel(s){
  if(!s) return '-';
  return `#${s.id} ${s.display_name || 'Speaker'} · ${s.sample_count || 0} samples · ${speakerConfidenceText(s)}`;
}
function preferredSpeakerMergeTarget(rows){
  const named = (rows || []).find(row => String(row.identity_status || '') === 'named');
  if(named) return String(named.id || '');
  return rows && rows.length ? String(rows[0].id || '') : '';
}
function speakerById(rows, id){
  if(!id) return null;
  return (rows || []).find(row => String(row.id) === String(id)) || null;
}
function speakerCard(s){
  const evidence = s.evidence || {};
  const review = speakerNeedsReview(s);
  const empty = Number(s.sample_count || 0) <= 0;
  const selected = speakerIsSelected(s.id);
  const reviewStatus = speakerReviewStatus(s);
  const confidence = speakerConfidenceSummary(s);
  return `<div class="speaker-card ${empty?'empty':review?'review':''} ${speakerIsHidden(s)?'hidden-speaker':''} ${selected?'selected':''}" onclick="toggleSpeakerSelection('${escAttr(s.id)}')">
    <input class="speaker-check" type="checkbox" ${selected?'checked':''} onclick="event.stopPropagation(); setSpeakerChecked('${escAttr(s.id)}', this.checked)" aria-label="select speaker ${escAttr(s.id)}">
    <div class="speaker-card-top">
      <div><div class="speaker-name">${esc(s.display_name || `Speaker ${s.id}`)}</div><div class="speaker-meta"><span>ID ${esc(s.id)}</span><span>${esc(shortDateTime(speakerVisibleTime(s)) || '-')}</span></div></div>
      ${speakerStatusBadge(reviewStatus || s.identity_status || 'info')}
    </div>
    ${speakerMergeSourceSummary(s)}
    <div class="speaker-card-metrics">
      <span><b>${esc(s.sample_count || 0)}</b> 样本</span>
      <span><b>${esc(evidence.day_count || 0)}</b> 天</span>
      <span title="${escAttr(confidence.detail || '')}"><b>${esc(speakerConfidenceText(s))}</b></span>
      <span>embedding ${esc(s.embedding_count || 0)}</span>
      <span>别名 ${esc(s.alias_count || 0)}</span>
      <span>最近 ${esc(shortDateTime(evidence.latest_seen_at || s.latest_sample_at || '-') || '-')}</span>
    </div>
  </div>`;
}
function speakerMergeSourceSummary(s){
  const sources = ((s.metadata || {}).auto_merge_sources || []).slice(-3).reverse();
  if(!sources.length && !speakerIsHidden(s)) return '';
  if(speakerIsHidden(s)) return `<div class="speaker-meta"><span>低相似自动隐藏</span><span>threshold ${esc(formatScore((s.metadata || {}).hidden_threshold))}</span></div>`;
  return `<div class="speaker-meta"><span>自动合并 ${esc((s.metadata || {}).auto_merge_sources.length)} 个来源</span><span>${sources.map(item => esc(`#${item.source_speaker_id || '-'} ${item.source_display_name || ''} ${formatScore(item.score)}`)).join(' · ')}</span></div>`;
}
function speakerSelectedIds(){
  if(!Array.isArray(state.speakerSelectedIds)) state.speakerSelectedIds = [];
  return state.speakerSelectedIds.map(String).filter(Boolean);
}
function speakerIsSelected(id){
  return speakerSelectedIds().includes(String(id));
}
function setSpeakerSelectedIds(ids){
  state.speakerSelectedIds = [...new Set((ids || []).map(id => String(id)).filter(Boolean))];
}
function toggleSpeakerSelection(id){
  const key = String(id || '');
  if(!key) return;
  const ids = speakerSelectedIds();
  if(ids.length === 1 && ids[0] === key){
    setSpeakerSelectedIds([]);
    state.speakerSamplesFor = 'visible';
    state.speakerContextSource = speakerFallbackContextSource();
  } else {
    setSpeakerSelectedIds([key]);
    state.speakerSamplesFor = 'selected';
    state.speakerContextSource = 'selection';
  }
  speakers();
}
function setSpeakerChecked(id, checked){
  const key = String(id || '');
  const ids = speakerSelectedIds();
  setSpeakerSelectedIds(checked ? [...ids, key] : ids.filter(item => item !== key));
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = 'selection';
  speakers();
}
function selectSpeakerForRename(id){
  setSpeakerSelectedIds(id ? [id] : []);
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = id ? 'selection' : speakerFallbackContextSource();
  speakers();
}
function selectVisibleSpeakers(){
  setSpeakerSelectedIds(state.speakerShownIds || []);
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = 'selection';
  speakers();
}
function invertVisibleSpeakers(){
  const shown = (state.speakerShownIds || []).map(String);
  const selected = new Set(speakerSelectedIds());
  shown.forEach(id => selected.has(id) ? selected.delete(id) : selected.add(id));
  setSpeakerSelectedIds([...selected]);
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = selected.size ? 'selection' : speakerFallbackContextSource();
  speakers();
}
function clearSpeakerSelection(){
  state.speakerSelectedIds = [];
  state.speakerBulkTarget = '';
  state.speakerSamplesFor = 'visible';
  state.speakerContextSource = speakerFallbackContextSource();
  speakers();
}
function renameSelectedSpeaker(){
  const speakerId = $('renameId')?.value || speakerSelectedIds()[0];
  const displayName = $('renameName')?.value || '';
  if(!speakerId || !displayName.trim()){
    toast('请选择说话人并输入显示名');
    return;
  }
  action('speaker_rename',{speaker_id:speakerId,display_name:displayName});
}
function autoOrganizeSpeakers(){
  const threshold = speakerAutoMergeThreshold();
  if(askConfirm(`自动整理相似声音：按当前配置阈值 ${formatScore(threshold)} 自动合并相似未命名 Voice；命名说话人只进入人工候选，并把低相似未命名 Voice 隐藏到单独筛选里？`)){
    action('speaker_auto_organize',{});
  }
}
function confirmSelectedSpeakers(){
  const ids = speakerSelectedIds();
  if(!ids.length){
    toast('请先勾选要确认的说话人');
    return;
  }
  action('speaker_confirm',{speaker_ids:ids});
}
function unhideSelectedSpeakers(){
  const ids = speakerSelectedIds();
  if(!ids.length){
    toast('请先勾选要取消隐藏的说话人');
    return;
  }
  action('speaker_unhide',{speaker_ids:ids});
}
function visibleSpeakerIds(){
  return (state.speakerShownIds || []).map(String).filter(Boolean);
}
function confirmVisibleSpeakers(){
  const ids = visibleSpeakerIds();
  if(!ids.length){
    toast('当前队列没有可处理的说话人');
    return;
  }
  if(askConfirm(`确认当前队列里的 ${ids.length} 个说话人？`)) action('speaker_confirm',{speaker_ids:ids});
}
function unhideVisibleSpeakers(){
  const ids = visibleSpeakerIds();
  if(!ids.length){
    toast('当前队列没有可处理的说话人');
    return;
  }
  if(askConfirm(`取消隐藏当前队列里的 ${ids.length} 个说话人？`)) action('speaker_unhide',{speaker_ids:ids});
}
function refreshVisibleSpeakerSampleConfidence(){
  const ids = visibleSpeakerIds();
  if(!ids.length){
    toast('当前队列没有可处理的说话人');
    return;
  }
  refreshSpeakerSampleConfidence(ids);
}
function focusedSampleSpeakerIds(){
  return (state.speakerFocusedSampleSpeakerIds || []).map(String).filter(Boolean);
}
function focusedSampleIds(){
  return (state.speakerFocusedSampleIds || []).map(String).filter(Boolean);
}
function selectFocusedSampleSpeakers(){
  const ids = focusedSampleSpeakerIds();
  if(!ids.length){
    toast('当前样本筛选没有关联说话人');
    return;
  }
  setSpeakerSelectedIds(ids);
  state.speakerSamplesFor = 'selected';
  state.speakerContextSource = 'selection';
  speakers();
}
function refreshFocusedSampleSpeakerConfidence(){
  const ids = focusedSampleSpeakerIds();
  if(!ids.length){
    toast('当前样本筛选没有关联说话人');
    return;
  }
  refreshSpeakerSampleConfidence(ids);
}
function refreshFocusedRepresentativeSamples(){
  const ids = focusedSampleSpeakerIds();
  if(!ids.length){
    toast('当前样本筛选没有关联说话人');
    return;
  }
  action('speaker_refresh_representatives',{speaker_ids:ids, per_speaker:3});
}
function repairFocusedSampleClips(){
  const ids = focusedSampleIds();
  if(!ids.length){
    toast('当前样本筛选没有可处理的样本');
    return;
  }
  if(askConfirm(`按当前裁剪策略重裁 ${ids.length} 个样本？只会处理能找到源音频的样本，已确认说话人不会被重新分组。`)){
    action('speaker_repair_sample_clips',{sample_ids:ids, apply:true});
  }
}
function bulkMergeSpeakers(){
  const ids = speakerSelectedIds();
  const selectedRows = (state.speakers || []).filter(row => ids.includes(String(row.id)));
  const targetId = $('bulkMergeTarget')?.value || state.speakerBulkTarget || preferredSpeakerMergeTarget(selectedRows) || ids[0] || '';
  const sourceIds = ids.filter(id => String(id) !== String(targetId));
  if(!targetId || sourceIds.length < 1){
    toast('至少勾选两个说话人，或选择一个合并目标');
    return;
  }
  if(askConfirm(`把 ${sourceIds.length} 个说话人合并到 ${targetId}？`)) action('speaker_merge_many',{target_id:targetId,source_ids:sourceIds});
}
function refreshSpeakerSampleConfidence(speakerIds=[]){
  const ids = (speakerIds || []).map(String).filter(Boolean);
  action('speaker_refresh_sample_confidence', ids.length ? {speaker_ids:ids} : {});
}
function refreshSelectedSpeakerSampleConfidence(){
  const ids = speakerSelectedIds();
  if(!ids.length){
    toast('未选择说话人，将重算全部说话人一致性');
  }
  refreshSpeakerSampleConfidence(ids);
}
function repairSpeakerEmbeddings(){
  if(askConfirm('为已有样本补齐缺失的 speaker embedding？这会调用本地 SpeechBrain 模型，可能需要一点时间。')){
    action('speaker_repair_embeddings',{apply:true});
  }
}
function refreshRepresentativeSamples(){
  const ids = speakerSelectedIds();
  action('speaker_refresh_representatives', ids.length ? {speaker_ids:ids, per_speaker:3} : {per_speaker:3});
}
function reviveHiddenSpeakers(){
  if(askConfirm('把隐藏队列里已经积累足够证据的 Voice 放回人工复查？')){
    action('speaker_revive_hidden',{apply:true,min_samples:2,min_days:2,min_embeddings:2});
  }
}
function bulkDeleteSpeakers(){
  const ids = speakerSelectedIds();
  if(!ids.length){
    toast('请先勾选要删除的说话人');
    return;
  }
  if(askConfirm(`删除 ${ids.length} 个说话人及其托管样本记录？这个操作不能撤销。`)) action('speaker_delete_many',{speaker_ids:ids});
}
function fillSpeakerRename(id, name){
  setSpeakerSelectedIds(id ? [id] : []);
  state.speakerSamplesFor = id ? 'selected' : 'visible';
  state.speakerContextSource = id ? 'selection' : speakerFallbackContextSource();
  if($('renameId')) $('renameId').value = id || '';
  if($('renameName')) $('renameName').value = name || '';
  toast(`已填入说话人 ${id}`);
}
function speakerProfilePanel(selectedRows, profiles){
  const selectedId = selectedRows.length === 1 ? String(selectedRows[0].id) : '';
  const profile = (profiles || []).find(item => String((item.speaker || {}).id) === selectedId) || (profiles || [])[0];
  if(!profile || profile.ok === false) return `<details class="card compact-details"><summary>人物档案</summary><div class="compact-details-body"><div class="empty-state">No active speaker profile</div></div></details>`;
  const speaker = profile.speaker || {};
  const confidence = profile.confidence || {};
  const stats = profile.stats || {};
  return `<details class="card compact-details">
    <summary>人物档案 · ${esc(speaker.display_name || `Speaker ${speaker.id}`)} · ${esc(confidence.label || '-')}</summary>
    <div class="compact-details-body">
    <div class="speaker-profile-head">
      <div class="speaker-name">${esc(speaker.display_name || `Speaker ${speaker.id}`)}</div>
      <div class="item-meta">ID ${esc(speaker.id)} · ${esc(stats.day_count || 0)} 天 · ${esc(profile.embedding_count || 0)} embeddings · ${speakerStatusBadge((speaker.metadata || {}).speaker_review_status || speaker.identity_status || 'info')}</div>
    </div>
    <div class="speaker-profile-note">${esc(confidence.detail || '')}</div>
    <div class="speaker-profile-block">
      <div class="speaker-action-title">代表样本</div>
      ${speakerSampleList(profile.representative_samples || [])}
    </div>
    <div class="speaker-profile-block">
      <div class="speaker-action-title">说话人时间线</div>
      ${speakerTimelineList(profile.timeline || [])}
    </div>
    </div>
  </details>`;
}
function speakerTimelineList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No speaker timeline yet</div>';
  return `<div class="speaker-match-list">${rows.slice(0, 8).map(item => `<div class="speaker-match-card">
    <div class="speaker-match-row"><div><b>${esc(shortDateTime(item.observed_at || '') || '-')}</b><div class="item-meta">${esc(item.source || '')}/${esc(item.kind || '')} · ${esc(formatSecondsRange(item.start_seconds, item.end_seconds))}</div></div></div>
    <div class="speaker-transcript">${esc(item.transcript || item.body || '')}</div>
  </div>`).join('')}</div>`;
}
function speakerSampleList(rows, options={}){
  if(!(rows || []).length) return '<div class="empty-state">No speaker samples yet</div>';
  const limit = Number(options.limit || 6);
  const shown = rows.slice(0, limit);
  const more = rows.length > limit ? `<div class="empty-state">还有 ${esc(rows.length - limit)} 个样本，可继续缩小筛选条件。</div>` : '';
  const body = `${shown.map(sample => {
    const sampleConfidence = sampleConfidenceText(sample);
    const rep = sampleIsRepresentative(sample) ? ' · 代表样本' : '';
    const cardClass = speakerSampleCardClass(sample);
    const badges = speakerSampleBadges(sample);
    return `<div class="speaker-sample-card ${cardClass}">
    <div class="speaker-match-row"><div><b>${esc(sample.speaker_name || sample.speaker_id)}</b><div class="item-meta">sample ${esc(sample.id || '-')} · ${esc(formatSecondsRange(sample.start_seconds, sample.end_seconds))} · obs ${esc(sample.observation_id || '-')}${sampleConfidence ? ` · ${sampleConfidence}` : ''}${esc(rep)}</div></div>${status((sample.metadata || {}).status || 'info')}</div>
    ${badges ? `<div class="speaker-sample-tags">${badges}</div>` : ''}
    <div class="speaker-transcript">${esc(sample.transcript || '')}</div>
    ${sample.sample_path ? `<audio controls preload="none"><source src="/api/speaker-sample/${escAttr(sample.id)}" type="audio/mp4"></audio>` : ''}
    <div class="speaker-sample-actions"><button class="btn" onclick="splitSpeakerSample('${escAttr(sample.id)}')">手动切分样本</button><button class="btn" onclick="detachSpeakerSample('${escAttr(sample.id)}')">分离成新说话人</button></div>
  </div>`;
  }).join('')}${more}`;
  return options.expanded ? body : `<div class="speaker-sample-list">${body}</div>`;
}
function sampleConfidenceText(sample){
  const n = sampleConfidenceValue(sample);
  return Number.isFinite(n) ? `样本一致性 ${formatPercent(n)}` : '';
}
function speakerSampleCardClass(sample){
  if(sampleHasError(sample)) return 'error';
  if(sampleHasLowConfidence(sample)) return 'low-confidence';
  if(sampleIsRepresentative(sample)) return 'representative';
  if(sampleMissingEmbedding(sample)) return 'missing-embedding';
  return 'ok';
}
function speakerSampleBadges(sample){
  const metadata = sample.metadata || {};
  const badges = [];
  if(sampleHasLowConfidence(sample)) badges.push(speakerStatusBadge('below_threshold'));
  if(sampleMissingEmbedding(sample)) badges.push('<span class="status skipped">缺 embedding</span>');
  if(sampleIsRepresentative(sample)) badges.push('<span class="status accepted">代表样本</span>');
  if(sampleIsDetached(sample)) badges.push('<span class="status info">已分离</span>');
  if(metadata.sample_role === 'manual_split_child') badges.push('<span class="status info">切分子样本</span>');
  if(metadata.sample_role === 'mixed_parent_archived') badges.push('<span class="status skipped">已归档母样本</span>');
  if(sample.sample_path) badges.push('<span class="status observation">可播放</span>');
  if(metadata.sample_role && !sampleIsDetached(sample) && !['manual_split_child', 'mixed_parent_archived'].includes(metadata.sample_role)) badges.push(`<span class="status info">${esc(metadata.sample_role)}</span>`);
  return badges.join('');
}
function detachSpeakerSample(sampleId){
  const sample = (state.speakerSamples || []).find(row => String(row.id) === String(sampleId));
  const current = sample ? (sample.speaker_name || sample.speaker_id || '当前说话人') : '当前说话人';
  if(askConfirm(`把这个样本从 ${current} 分离出来，并单独新建一个 Voice？`)){
    action('speaker_detach_sample', {sample_id: sampleId});
  }
}
function splitSpeakerSample(sampleId){
  const sample = (state.speakerSamples || []).find(row => String(row.id) === String(sampleId));
  const duration = sample ? (Number(sample.end_seconds) - Number(sample.start_seconds)) : NaN;
  const midpoint = Number.isFinite(duration) && duration > 1 ? (duration / 2).toFixed(2) : '';
  const cuts = prompt('输入切分点，单位为当前 sample 内的秒数。多个点用逗号分隔。', midpoint);
  if(!cuts || !cuts.trim()) return;
  if(!askConfirm(`按 ${cuts} 秒切分这个 sample？每段会先新建 Voice，原 sample 会归档。`)) return;
  action('speaker_split_sample', {sample_id: sampleId, cuts});
}
window.detachSpeakerSample = detachSpeakerSample;
window.splitSpeakerSample = splitSpeakerSample;
function speakerMatchList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No match decisions</div>';
  return `<div class="speaker-match-list">${rows.slice(0, 12).map(match => `<div class="speaker-match-card">
    <div class="speaker-match-row"><div><b>${esc(match.source_name || match.source_speaker_id)}</b><div class="item-meta">to ${esc(match.target_name || match.target_speaker_id || '-')}</div></div>${speakerStatusBadge(match.status || 'info')}</div>
    <div class="speaker-meta"><span>${esc(shortDateTime(match.created_at || ''))}</span><span class="speaker-score">score ${esc(formatScore(match.score))}</span><span>threshold ${esc(formatScore(match.threshold))}</span></div>
    ${match.source_speaker_id && match.target_speaker_id ? `<div style="margin-top:8px"><button class="btn" onclick="selectSpeakerMatchGroup('${escAttr(match.source_speaker_id)}','${escAttr(match.target_speaker_id)}')">勾选这组</button></div>` : ''}
  </div>`).join('')}</div>`;
}
function selectSpeakerMatchGroup(sourceId, targetId){
  setSpeakerSelectedIds([sourceId, targetId]);
  state.speakerBulkTarget = targetId || '';
  state.speakerSamplesFor = 'selected';
  speakers();
}
function formatPercent(value){
  const n = Number(value);
  return Number.isFinite(n) ? `${Math.round(n * 100)}%` : '-';
}
function formatSecondsRange(start, end){
  const a = Number(start);
  const b = Number(end);
  if(!Number.isFinite(a) || !Number.isFinite(b)) return '-';
  return `${a.toFixed(1)}s-${b.toFixed(1)}s`;
}
async function files(){
  setHeader('文件','读取中...', `<button class="btn primary" onclick="action('analyze_new_files',{})">扫描新文件</button><button class="btn" onclick="go('recycle')">回收箱</button><button class="btn" onclick="files()">刷新</button>`);
  const j=await api('/api/files');
  const cfg = j.file_analysis || {};
  const rows = j.recent || [];
  const shown = filterFileRecords(rows);
  const fileState = j.state || {};
  const stateData = fileState.data || {};
  const processedCount = Object.keys(stateData.processed_keys || {}).length;
  $('subtitle').textContent = `${(j.watch_paths || []).length} 个路径 · ${escText(j.media_analysis_count || 0)} 个分析 · ${shown.length}/${rows.length} 条记录`;
  $('view').innerHTML = `
    <div class="files-hero">
      <div class="card">
        <div class="section-title"><h3>分析状态</h3>${status(cfg.enabled ? 'ok' : 'disabled')}</div>
        <div class="file-kpis">
          ${fileKpi('文件分析', cfg.enabled ? '开启' : '关闭', `${cfg.scan_interval_seconds ?? '-'} 秒扫描`)}
          ${fileKpi('已分析', j.media_analysis_count || 0, 'local_ai/media_analysis')}
          ${fileKpi('监控路径', (j.watch_paths || []).length, `${cfg.max_files_per_scan ?? '-'} 个/轮`)}
          ${fileKpi('已处理', processedCount, `上次 ${formatEpoch(stateData.last_scan_ts)}`)}
        </div>
        ${fileFilterPills(rows)}
      </div>
      <div class="card">
        <div class="section-title"><h3>扫描控制</h3><span class="muted">${esc(formatBool(cfg.delete_after_analysis))}</span></div>
        ${fileConfigRows(cfg)}
        <div class="overview-actions" style="margin-top:12px">
          <button class="btn primary" onclick="action('analyze_new_files',{})">扫描新文件</button>
          <button class="btn" onclick="go('recycle')">查看回收箱</button>
        </div>
      </div>
    </div>
    <div class="file-main">
      <div>
        <div class="section-title"><h3>最近文件记录</h3><span class="muted">${esc(shown.length)} shown</span></div>
        <div class="file-toolbar">
          <input id="fileQ" value="${esc(state.fileQ)}" placeholder="搜索文件名、路径、正文、source/kind" aria-label="file search" onkeydown="fileSearchKey(event)">
          <button class="btn primary" onclick="applyFileSearch()">查找</button>
        </div>
        ${fileRecordList(shown)}
      </div>
      <div class="file-side">
        <div class="card">
          <div class="section-title"><h3>监控路径</h3><span class="muted">${esc((j.watch_paths || []).length)} paths</span></div>
          ${filePathList(j.watch_paths || [])}
        </div>
        <div class="card">
          <div class="section-title"><h3>格式规则</h3><span class="muted">${esc((cfg.include_suffixes || []).length)} include</span></div>
          ${fileRulePanel(cfg)}
        </div>
        <div class="card">
          <div class="section-title"><h3>状态文件</h3>${status(fileState.exists ? 'ok' : 'missing_file')}</div>
          ${fileStatePanel(fileState)}
        </div>
      </div>
    </div>`;
}
function applyFileSearch(){
  state.fileQ = $('fileQ').value;
  files();
}
function fileSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyFileSearch();
  }
}
function setFileView(value){
  state.fileView = value || 'all';
  files();
}
function filterFileRecords(rows){
  const q = String(state.fileQ || '').trim().toLowerCase();
  return (rows || []).filter(row => {
    if(!fileViewMatch(row, state.fileView)) return false;
    if(!q) return true;
    const haystack = [row.title, row.subtitle, row.source, row.kind, row.body, row.summary, row.snippet, row.source_key, fileRecordPath(row)].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function fileViewMatch(row, view){
  if(!view || view === 'all') return true;
  if(view === 'filesystem') return row.source === 'filesystem';
  if(view === 'analysis') return fileIsAnalysis(row);
  if(view === 'with_body') return Boolean(row.body || row.summary || row.snippet);
  if(view === 'large') return fileRecordSize(row) >= 10 * 1024 * 1024;
  return true;
}
function fileFilterPills(rows){
  const views = [
    ['all', '全部', (rows || []).length],
    ['filesystem', '文件事件', (rows || []).filter(row => row.source === 'filesystem').length],
    ['analysis', '已有分析', (rows || []).filter(fileIsAnalysis).length],
    ['with_body', '有正文', (rows || []).filter(row => row.body || row.summary || row.snippet).length],
    ['large', '大文件', (rows || []).filter(row => fileRecordSize(row) >= 10 * 1024 * 1024).length],
  ];
  return `<div class="file-filters">${views.map(([key,label,count]) => `<button class="filter-pill ${state.fileView===key?'active':''}" onclick="setFileView('${escAttr(key)}')">${esc(label)} ${esc(count)}</button>`).join('')}</div>`;
}
function fileKpi(label, value, hint){
  return `<div class="file-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function fileConfigRows(cfg){
  const rows = [
    ['扫描间隔', `${cfg.scan_interval_seconds ?? '-'} 秒`],
    ['稳定等待', `${cfg.stability_seconds ?? '-'} 秒`],
    ['每轮上限', cfg.max_files_per_scan ?? '-'],
    ['分析后删除', formatBool(cfg.delete_after_analysis)],
    ['工作区', cfg.analysis_copy_dir || '-'],
  ];
  return `<div class="file-config-list">${rows.map(([label,value]) => `<div class="queue-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function fileRecordList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No file records match this filter</div>';
  return `<div class="file-list">${rows.slice(0, 80).map(fileRecordCard).join('')}</div>`;
}
function fileRecordCard(row){
  const path = fileRecordPath(row);
  const size = fileRecordSize(row);
  return `<div class="file-card ${esc(fileRecordClass(row))}">
    <div class="file-time">${esc(shortDateTime(row.observed_at || row.captured_at || ''))}${row.captured_at?`<br><span class="muted">captured ${esc(shortDateTime(row.captured_at))}</span>`:''}</div>
    <div>${fileRecordBadge(row)}<div class="item-meta" style="margin-top:6px">ID ${esc(row.id || '-')}</div></div>
    <div>
      <div class="file-title">${esc(row.title || row.kind || 'File record')}</div>
      <div class="file-meta"><span>${esc(row.source || '')}/${esc(row.kind || '')}</span>${size?`<span>${esc(bytes(size))}</span>`:''}${path?`<span>${esc(shortPath(path))}</span>`:''}</div>
      <div class="file-body">${esc(row.body || row.summary || row.snippet || path || '文件变更记录')}</div>
    </div>
  </div>`;
}
function fileRecordBadge(row){
  if(fileIsAnalysis(row)) return '<span class="status ok">分析</span>';
  if(row.source === 'filesystem') return '<span class="status observation">文件事件</span>';
  return `<span class="status skipped">${esc(row.source || 'record')}</span>`;
}
function fileRecordClass(row){
  if(fileIsAnalysis(row)) return 'analysis';
  if(row.source === 'filesystem') return 'filesystem';
  return 'other';
}
function fileIsAnalysis(row){
  return row.source === 'local_ai' || row.source === 'openai' || row.kind === 'media_analysis';
}
function fileRecordPath(row){
  const meta = row.metadata || {};
  return meta.path || meta.file_path || meta.resolved_media_path || row.source_key || row.subtitle || '';
}
function fileRecordSize(row){
  const meta = row.metadata || {};
  return Number(meta.size || meta.file_size || meta.bytes || 0);
}
function filePathList(paths){
  if(!(paths || []).length) return '<div class="empty-state">No watch paths configured</div>';
  return `<div class="file-path-list">${paths.map(path => `<div class="file-path-row"><div class="file-path-title">${esc(shortPath(path) || path)}</div><div class="item-meta">${esc(path)}</div></div>`).join('')}</div>`;
}
function fileRulePanel(cfg){
  return `<div>
    <div class="item-meta">支持格式</div>
    ${fileChipList(cfg.include_suffixes || [])}
    <div class="item-meta" style="margin-top:12px">跳过格式</div>
    ${fileChipList(cfg.exclude_suffixes || [])}
    <div class="item-meta" style="margin-top:12px">跳过目录</div>
    ${fileChipList(cfg.exclude_dirs || [])}
  </div>`;
}
function fileChipList(items){
  if(!(items || []).length) return '<div class="muted">-</div>';
  return `<div class="file-chip-row">${items.map(item => `<span class="file-chip">${esc(item)}</span>`).join('')}</div>`;
}
function fileStatePanel(fileState){
  if(!fileState || !fileState.exists) return '<div class="empty-state">No file analysis state yet</div>';
  const data = fileState.data || {};
  const processed = Object.keys(data.processed_keys || {}).length;
  const rows = [
    ['文件', shortPath(fileState.path || '-')],
    ['last_scan_ts', formatEpoch(data.last_scan_ts)],
    ['watermark', formatEpoch(data.watermark)],
    ['processed_keys', processed],
  ];
  return `<div class="file-state-list">${rows.map(([label,value]) => `<div class="file-state-row"><div class="file-state-title">${esc(label)}</div><div class="item-meta">${esc(value)}</div></div>`).join('')}</div>`;
}
function formatBool(value){
  return value ? '开启' : '关闭';
}
function formatEpoch(value){
  const n = Number(value);
  if(!Number.isFinite(n) || n <= 0) return '-';
  return new Date(n * 1000).toLocaleString('zh-CN', {hour12: false});
}
async function recycle(){
  setHeader('回收箱','读取中...',
    `<button class="btn" onclick="go('files')">文件</button><button class="btn" onclick="action('recycle_purge',{})">预览清理</button><button class="btn danger" onclick="askConfirm('永久删除已到期的回收箱文件？') && action('recycle_purge',{apply:true})">清理到期</button><button class="btn primary" onclick="recycle()">刷新</button>`);
  const j=await api('/api/recycle-bin');
  const entries = j.entries || [];
  const shown = filterRecycleEntries(entries);
  const summary = j.summary || {};
  const config = j.config || {};
  const preview = j.purge_preview || {};
  const nextDelete = summary.next_delete_after ? shortDateTime(summary.next_delete_after) : '-';
  $('subtitle').textContent = `${summary.files || 0} 个文件 · ${bytes(summary.total_bytes || 0)} · ${summary.due_files || 0} 到期 · 下次 ${nextDelete}`;
  $('view').innerHTML = `
    <div class="recycle-hero">
      <div class="card">
        <div class="section-title"><h3>暂存概览</h3>${status(config.enabled ? 'ok' : 'disabled')}</div>
        <div class="recycle-kpis">
          ${recycleKpi('暂存文件', summary.files || 0, `${summary.manifests || 0} manifests`)}
          ${recycleKpi('占用空间', bytes(summary.total_bytes || 0), `${summary.orphan_manifests || 0} orphan`)}
          ${recycleKpi('到期可删', summary.due_files || 0, `${bytes(preview.freed_bytes || 0)} 可释放`)}
          ${recycleKpi('保留期', `${config.retention_hours ?? 24}h`, `下次 ${nextDelete}`)}
        </div>
        ${recycleFilterPills(entries)}
      </div>
      <div class="card">
        <div class="section-title"><h3>清理预览</h3><span class="muted">${esc(preview.deleted_files || 0)} files</span></div>
        ${recyclePreviewPanel(preview)}
        <div class="recycle-actions" style="margin-top:12px">
          <button class="btn" onclick="action('recycle_purge',{})">预览清理</button>
          <button class="btn danger" onclick="askConfirm('永久删除已到期的回收箱文件？') && action('recycle_purge',{apply:true})">清理到期</button>
        </div>
      </div>
    </div>
    <div class="recycle-main">
      <div>
        <div class="section-title"><h3>回收文件</h3><span class="muted">${esc(shown.length)} shown</span></div>
        <div class="recycle-toolbar">
          <input id="recycleQ" value="${esc(state.recycleQ)}" placeholder="搜索文件名、原路径、回收路径、分类" aria-label="recycle search" onkeydown="recycleSearchKey(event)">
          <button class="btn primary" onclick="applyRecycleSearch()">查找</button>
        </div>
        ${recycleEntryList(shown)}
      </div>
      <div class="recycle-side">
        <div class="card">
          <div class="section-title"><h3>恢复</h3><span class="muted">${esc(shortPath(config.dir || ''))}</span></div>
          ${recycleRestorePanel()}
        </div>
        <div class="card">
          <div class="section-title"><h3>分类</h3><span class="muted">${esc(entries.length)} entries</span></div>
          ${recycleCategoryBreakdown(entries)}
        </div>
        <div class="card">
          <div class="section-title"><h3>配置</h3>${status(config.enabled ? 'ok' : 'disabled')}</div>
          ${recycleConfigPanel(config)}
        </div>
      </div>
    </div>`;
}
function applyRecycleSearch(){
  state.recycleQ = $('recycleQ').value;
  recycle();
}
function recycleSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applyRecycleSearch();
  }
}
function setRecycleView(value){
  state.recycleView = value || 'all';
  recycle();
}
function filterRecycleEntries(entries){
  const q = String(state.recycleQ || '').trim().toLowerCase();
  return (entries || []).filter(entry => {
    if(!recycleViewMatch(entry, state.recycleView)) return false;
    if(!q) return true;
    const metadata = entry.metadata || {};
    const haystack = [entry.name, entry.category, entry.original_path, entry.trash_path, entry.moved_at, entry.delete_after, metadata.reason, metadata.import_root].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function recycleViewMatch(entry, view){
  if(!view || view === 'all') return true;
  if(view === 'due') return recycleIsDue(entry);
  if(view === 'retained') return entry.exists !== false && !recycleIsDue(entry);
  if(view === 'missing') return entry.exists === false;
  if(view === 'mobile') return recycleIsMobile(entry);
  if(view === 'unknown') return String(entry.category || 'unknown') === 'unknown';
  return true;
}
function recycleFilterPills(entries){
  const rows = [
    ['all', '全部', (entries || []).length],
    ['due', '到期', (entries || []).filter(recycleIsDue).length],
    ['retained', '保留中', (entries || []).filter(entry => entry.exists !== false && !recycleIsDue(entry)).length],
    ['mobile', '手机音频', (entries || []).filter(recycleIsMobile).length],
    ['missing', '缺失', (entries || []).filter(entry => entry.exists === false).length],
    ['unknown', '未知', (entries || []).filter(entry => String(entry.category || 'unknown') === 'unknown').length],
  ];
  return `<div class="recycle-filters">${rows.map(([key,label,count]) => `<button class="filter-pill ${state.recycleView===key?'active':''}" onclick="setRecycleView('${escAttr(key)}')">${esc(label)} ${esc(count)}</button>`).join('')}</div>`;
}
function recycleKpi(label, value, hint){
  return `<div class="recycle-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function recycleEntryList(entries){
  if(!(entries || []).length) return '<div class="empty-state">No recycled files match this filter</div>';
  return `<div class="recycle-list">${entries.slice(0, 120).map(recycleEntryCard).join('')}</div>`;
}
function recycleEntryCard(entry){
  const original = entry.original_path || '';
  const trash = entry.trash_path || '';
  return `<div class="recycle-card ${esc(recycleCardClass(entry))}">
    <div class="recycle-time">${esc(shortDateTime(entry.moved_at || ''))}<br><span class="muted">${esc(shortDateTime(entry.delete_after || ''))}</span></div>
    <div>${recycleStatusBadge(entry)}<div class="item-meta" style="margin-top:6px">${esc(bytes(entry.size || 0))}</div></div>
    <div>
      <div class="recycle-title">${esc(entry.name || shortPath(trash) || 'Recycled file')}</div>
      <div class="recycle-meta"><span>${esc(recycleCategoryLabel(entry.category))}</span><span>${esc(recycleTimeLeft(entry))}</span>${entry.manifest_path?'<span>manifest</span>':'<span>no manifest</span>'}</div>
      <div class="recycle-path">${esc(original || '原路径未知')}<br>${esc(trash)}</div>
    </div>
    <button class="btn" onclick="fillRecycleRestore('${escAttr(trash)}','${escAttr(original)}')">填入</button>
  </div>`;
}
function recycleStatusBadge(entry){
  if(entry.exists === false) return '<span class="status missing_file">缺失</span>';
  if(recycleIsDue(entry)) return '<span class="status warn">到期</span>';
  return '<span class="status ok">保留中</span>';
}
function recycleCardClass(entry){
  if(entry.exists === false) return 'missing';
  if(recycleIsDue(entry)) return 'due';
  if(String(entry.category || 'unknown') === 'unknown') return 'unknown';
  return 'retained';
}
function recycleIsDue(entry){
  const ts = Date.parse(entry.delete_after || '');
  return Number.isFinite(ts) && ts <= Date.now();
}
function recycleIsMobile(entry){
  const category = String(entry.category || '');
  return category.startsWith('mobile') || String(entry.original_path || '').includes('/mobile_sync/');
}
function recycleTimeLeft(entry){
  const ts = Date.parse(entry.delete_after || '');
  if(!Number.isFinite(ts)) return '无到期时间';
  const diff = ts - Date.now();
  if(diff <= 0) return '已到期';
  return `${formatDuration(diff)} 后到期`;
}
function recyclePreviewPanel(preview){
  const rows = [
    ['删除文件', preview.deleted_files || 0],
    ['删除 manifest', preview.deleted_manifests || 0],
    ['空目录', preview.deleted_dirs || 0],
    ['可释放', bytes(preview.freed_bytes || 0)],
    ['保留文件', preview.retained_files || 0],
  ];
  return `<div class="recycle-preview-list">${rows.map(([label,value]) => `<div class="recycle-preview-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function recycleRestorePanel(){
  return `<div class="recycle-form">
    <input id="trashPath" placeholder="回收文件路径">
    <input id="restoreTo" placeholder="恢复到指定路径，可留空">
    <button class="btn primary" onclick="restoreRecycle($('trashPath').value,$('restoreTo').value)">恢复</button>
  </div>`;
}
function fillRecycleRestore(trashPath, originalPath=''){
  if($('trashPath')) $('trashPath').value = trashPath || '';
  if($('restoreTo')) $('restoreTo').value = originalPath || '';
  toast('已填入恢复路径');
}
function recycleCategoryBreakdown(entries){
  const counts = countBy(entries || [], entry => recycleCategoryLabel(entry.category));
  const rows = Object.entries(counts).sort(([,a],[,b]) => Number(b || 0) - Number(a || 0));
  if(!rows.length) return '<div class="empty-state">No recycle categories</div>';
  return `<div class="recycle-category-list">${rows.map(([label,count]) => `<div class="recycle-category-row"><span>${esc(label)}</span><span class="queue-value">${esc(count)}</span></div>`).join('')}</div>`;
}
function recycleConfigPanel(config){
  const rows = [
    ['路径', shortPath(config.dir || '-')],
    ['保留期', `${config.retention_hours ?? 24}h`],
    ['扫描清理', formatBool(config.purge_on_scan)],
    ['维护清理', formatBool(config.purge_on_agent_maintenance)],
  ];
  return `<div class="file-config-list">${rows.map(([label,value]) => `<div class="queue-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function recycleCategoryLabel(value){
  return ({mobile_audio_analysis:'手机音频分析', file_analysis:'文件分析', unknown:'未知'})[value] || value || '未知';
}
function formatDuration(ms){
  const totalMinutes = Math.max(0, Math.round(Number(ms || 0) / 60000));
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if(hours >= 24) return `${Math.floor(hours / 24)}天${hours % 24}小时`;
  if(hours > 0) return `${hours}小时${minutes}分`;
  return `${minutes}分`;
}
function restoreRecycle(trashPath, to=''){
  if(!trashPath) return toast('Missing trash path');
  action('recycle_restore',{trash_path:trashPath,to});
}
function mobileKindLabel(kind){
  return ({audio_segment:'录音片段', status:'状态', upload:'上传'})[kind] || kind || '手机事件';
}
function mobileAudioPanel(audio){
  const statuses = audio.statuses || {};
  const statusRows = Object.entries(statuses).sort(([,a],[,b]) => Number(b || 0) - Number(a || 0));
  return `<div>
    <div class="mobile-audio-grid">
      ${mobileAudioStat('总数', audio.total || 0)}
      ${mobileAudioStat('Pending', audio.pending || 0)}
      ${mobileAudioStat('Error', audio.errors || 0)}
    </div>
    <div class="mobile-storage-list" style="margin-top:10px">
      <div class="mobile-row"><span>Latest analyzed</span><span class="queue-value">${esc(shortDateTime(audio.latest_analyzed || '-'))}</span></div>
      ${statusRows.map(([key,count]) => `<div class="mobile-row"><span>${esc(key)}</span><span class="queue-value">${esc(count)}</span></div>`).join('')}
    </div>
  </div>`;
}
function mobileAudioStat(label, value){
  return `<div class="mobile-audio-stat"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`;
}
function mobileStoragePanel(storage){
  const rows = [
    ['Inbox files', storage.inbox_files || 0],
    ['Inbox size', bytes(storage.inbox_size || 0)],
    ['Import dirs', storage.import_dirs || 0],
    ['Imports size', bytes(storage.imports_size || 0)],
    ['Latest inbox', shortDateTime(storage.latest_inbox_at || '-')],
    ['Latest import', shortDateTime(storage.latest_import_at || '-')],
  ];
  return `<div class="mobile-storage-list">${rows.map(([label,value]) => `<div class="mobile-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function mobileCleanupPanel(cleanup){
  if(!cleanup) return '<div class="empty-state">No cleanup preview</div>';
  const rows = [
    ['删除文件', cleanup.deleted_files || 0],
    ['删除目录', cleanup.deleted_dirs || 0],
    ['可释放', bytes(cleanup.freed_bytes || 0)],
    ['保留 import', cleanup.retained_import_dirs || 0],
  ];
  return `<div class="mobile-cleanup-list">${rows.map(([label,value]) => `<div class="mobile-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function mobileFailureList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No audio failures</div>';
  return `<div class="mobile-failure-list">${rows.map(row => `<div class="source-issue fail"><div class="source-issue-title">${esc(row.title || 'Audio failure')}</div><div class="source-issue-body">${esc(shortDateTime(row.observed_at || ''))} · ${esc(row.error || '')}</div></div>`).join('')}</div>`;
}
function mobileConfigPanel(config){
  const rows = [
    ['Host', config.host || '-'],
    ['Port', config.port || '-'],
    ['Max upload', `${config.max_upload_mb || '-'} MB`],
    ['Write reports', formatBool(config.write_reports)],
    ['Analyze after import', formatBool(config.analyze_after_import)],
    ['Delete uploads', formatBool(config.delete_uploads_after_import)],
    ['Delete analyzed audio', formatBool(config.delete_audio_after_analysis)],
  ];
  return `<div class="mobile-config-list">${rows.map(([label,value]) => `<div class="mobile-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
async function sync(){
  setHeader('手机同步','读取中...', `<button class="btn" onclick="action('analyze_audio',{limit:20})">分析音频</button><button class="btn" onclick="action('install_sync_agent',{})">重载服务</button><button class="btn primary" onclick="sync()">刷新</button>`);
  const j=await api('/api/sync');
  const health = j.health || j.sync_health || {};
  const syncOk = !!j.mac_online && health.ok !== false && !health.error;
  const audio = j.audio || {};
  const storage = j.storage || {};
  const cleanup = j.cleanup_preview || {};
  const rows = j.recent_mobile || [];
  const shown = filterSyncEvents(rows);
  const lastObserved = j.last_mobile_observed_at || '-';
  const lastCaptured = j.last_mobile_captured_at || '-';
  $('subtitle').textContent = `${syncOk ? '在线' : '需检查'} · latest ${shortDateTime(lastCaptured)} · ${shown.length}/${rows.length} 条`;
  $('view').innerHTML = `
    <div class="sync-hero">
      <div class="card">
        <div class="section-title"><h3>连接与导入</h3>${status(syncOk?'ok':'warn')}</div>
        <div class="sync-kpis">
          ${syncKpi('Mac', syncOk ? '在线' : '需检查', syncEndpoint(j))}
          ${syncKpi('上次捕获', shortDateTime(lastCaptured), `observed ${shortDateTime(lastObserved)}`)}
          ${syncKpi('待导入', j.pending_server_import_files || 0, `${bytes(storage.inbox_size || 0)} inbox`)}
          ${syncKpi('音频分析', audio.complete ? '完成' : '待处理', `${audio.pending || 0} pending / ${audio.errors || 0} error`)}
        </div>
        ${syncFilterPills(rows)}
      </div>
      <div class="card">
        <div class="section-title"><h3>服务与操作</h3>${status(syncOk?'ok':'warn')}</div>
        <div class="sync-actions" style="margin-top:12px">
          <button class="btn primary" onclick="sync()">刷新</button>
          <button class="btn" onclick="action('analyze_audio',{limit:20})">分析音频</button>
          <button class="btn" onclick="action('install_sync_agent',{})">重载服务</button>
          <button class="btn" onclick="go('doctor')">诊断</button>
        </div>
        <details class="compact-details" style="margin-top:12px">
          <summary>服务详情</summary>
          <div class="compact-details-body">${syncHealthPanel(j)}</div>
        </details>
      </div>
    </div>
    <div class="sync-main">
      <div>
        <div class="section-title"><h3>最近移动端记录</h3><span class="muted">${esc(shown.length)} shown</span></div>
        <div class="sync-toolbar">
          <input id="syncQ" value="${esc(state.syncQ)}" placeholder="搜索时间、设备、正文、source key" aria-label="sync search" onkeydown="syncSearchKey(event)">
          <button class="btn primary" onclick="applySyncSearch()">查找</button>
        </div>
        ${syncEventList(shown)}
      </div>
      <div class="sync-side">
        <div class="card">
          <div class="section-title"><h3>音频分析</h3>${status(audio.complete ? 'ok' : 'warn')}</div>
          ${mobileAudioPanel(audio)}
        </div>
        <details class="card compact-details">
          <summary>上传与导入缓存 · ${esc(bytes((storage.inbox_size || 0) + (storage.imports_size || 0)))}</summary>
          <div class="compact-details-body">${syncStoragePanel(storage)}</div>
        </details>
        <details class="card compact-details">
          <summary>清理预览 · ${esc(bytes(cleanup.freed_bytes || 0))}</summary>
          <div class="compact-details-body">
            ${syncCleanupPanel(cleanup)}
            <div class="sync-actions" style="margin-top:12px">
              <button class="btn" onclick="action('mobile_cleanup',{})">清理预览</button>
              <button class="btn danger" onclick="askConfirm('执行移动端缓存清理？') && action('mobile_cleanup',{apply:true})">执行清理</button>
            </div>
          </div>
        </details>
        ${(j.failures || []).length ? `<div class="card">
          <div class="section-title"><h3>失败原因</h3><span class="muted">${esc((j.failures || []).length)}</span></div>
          ${mobileFailureList(j.failures || [])}
        </div>` : ''}
        <details class="card compact-details">
          <summary>导入策略 · ${esc((j.config || {}).service_name || 'Wond')}</summary>
          <div class="compact-details-body">${syncConfigPanel(j.config || {})}</div>
        </details>
      </div>
    </div>`;
}
function applySyncSearch(){
  state.syncQ = $('syncQ').value;
  sync();
}
function syncSearchKey(event){
  if(event.key === 'Enter'){
    event.preventDefault();
    applySyncSearch();
  }
}
function setSyncView(value){
  state.syncView = value || 'all';
  sync();
}
function filterSyncEvents(rows){
  const q = String(state.syncQ || '').trim().toLowerCase();
  return (rows || []).filter(row => {
    if(!syncViewMatch(row, state.syncView)) return false;
    if(!q) return true;
    const haystack = [row.observed_at, row.captured_at, row.kind, row.title, row.subtitle, row.body, row.source_key, row.location].map(value => String(value || '').toLowerCase()).join(' ');
    return haystack.includes(q);
  });
}
function syncViewMatch(row, view){
  if(!view || view === 'all') return true;
  if(view === 'audio') return row.kind === 'audio_segment';
  if(view === 'watch') return syncIsWatch(row);
  if(view === 'iphone') return syncIsIphone(row);
  if(view === 'recent') return Date.now() - Date.parse(row.captured_at || row.observed_at || '') <= 24 * 60 * 60 * 1000;
  if(view === 'text') return Boolean(row.body || row.summary || row.snippet);
  return true;
}
function syncFilterPills(rows){
  const values = [
    ['all', '全部', (rows || []).length],
    ['audio', '录音', (rows || []).filter(row => row.kind === 'audio_segment').length],
    ['iphone', 'iPhone', (rows || []).filter(syncIsIphone).length],
    ['watch', 'Watch', (rows || []).filter(syncIsWatch).length],
    ['recent', '24小时', (rows || []).filter(row => syncViewMatch(row, 'recent')).length],
    ['text', '有正文', (rows || []).filter(row => row.body || row.summary || row.snippet).length],
  ];
  return `<div class="sync-filters">${values.map(([key,label,count]) => `<button class="filter-pill ${state.syncView===key?'active':''}" onclick="setSyncView('${escAttr(key)}')">${esc(label)} ${esc(count)}</button>`).join('')}</div>`;
}
function syncKpi(label, value, hint){
  const compact = String(value ?? '').length > 10;
  return `<div class="sync-kpi"><div class="label">${esc(label)}</div><div class="value ${compact?'compact':''}">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function syncEndpoint(j){
  const health = j.health || {};
  const config = j.config || {};
  if(health.url) return health.url.replace('http://', '');
  return `port ${config.port || 8765}`;
}
function syncHealthPanel(j){
  const health = j.health || {};
  const config = j.config || {};
  const rows = [
    ['Service', health.service || config.service_name || '-'],
    ['Health', health.ok && !health.error ? 'OK' : (health.error || 'Issue')],
    ['URL', health.url || `http://127.0.0.1:${config.port || 8765}/health`],
    ['Host', config.host || '-'],
    ['Token', config.token ? 'configured' : 'empty'],
  ];
  return `<div class="sync-health-list">${rows.map(([label,value]) => `<div class="sync-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function syncEventList(rows){
  if(!(rows || []).length) return '<div class="empty-state">No mobile sync records match this filter</div>';
  return `<div class="sync-event-list">${rows.slice(0, 80).map(syncEventCard).join('')}</div>`;
}
function syncEventCard(row){
  const device = syncDeviceLabel(row);
  return `<div class="sync-event-card ${esc(syncEventClass(row))}">
    <div class="sync-time">${esc(shortDateTime(row.observed_at || ''))}${row.ended_at?`<br><span class="muted">${esc(shortDateTime(row.ended_at))}</span>`:''}</div>
    <div>${syncKindBadge(row)}<div class="item-meta" style="margin-top:6px">${esc(device)}</div></div>
    <div>
      <div class="sync-title">${esc(row.title || mobileKindLabel(row.kind))}</div>
      <div class="sync-meta"><span>${esc(row.source_key || row.kind || '')}</span><span>${esc(row.captured_at ? `captured ${shortDateTime(row.captured_at)}` : '')}</span></div>
      <div class="sync-body">${esc(row.body || row.location || row.subtitle || '')}</div>
    </div>
  </div>`;
}
function syncKindBadge(row){
  if(row.kind === 'audio_segment') return '<span class="status observation">录音</span>';
  return `<span class="status skipped">${esc(mobileKindLabel(row.kind))}</span>`;
}
function syncEventClass(row){
  if(syncIsWatch(row)) return 'watch';
  if(row.kind === 'audio_segment') return 'audio';
  return 'other';
}
function syncDeviceLabel(row){
  if(syncIsWatch(row)) return 'Apple Watch';
  if(syncIsIphone(row)) return 'iPhone';
  return row.subtitle || 'mobile';
}
function syncIsWatch(row){
  const text = `${row.subtitle || ''} ${row.source_key || ''}`.toLowerCase();
  return text.includes('watch');
}
function syncIsIphone(row){
  const text = `${row.subtitle || ''} ${row.source_key || ''}`.toLowerCase();
  return text.includes('iphone') || text.includes('ios-');
}
function syncStoragePanel(storage){
  return `<div>
    <div class="sync-storage-grid">
      ${syncStorageTile('Inbox files', storage.inbox_files || 0, bytes(storage.inbox_size || 0))}
      ${syncStorageTile('Import dirs', storage.import_dirs || 0, bytes(storage.imports_size || 0))}
      ${syncStorageTile('Retained', storage.retained_import_dirs || 0, 'import dirs')}
      ${syncStorageTile('Total', bytes((storage.inbox_size || 0) + (storage.imports_size || 0)), 'cache size')}
    </div>
  </div>`;
}
function syncStorageTile(label, value, hint){
  return `<div class="sync-storage-tile"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function syncCleanupPanel(cleanup){
  if(!cleanup) return '<div class="empty-state">No cleanup preview</div>';
  const rows = [
    ['删除文件', cleanup.deleted_files || 0],
    ['删除目录', cleanup.deleted_dirs || 0],
    ['可释放', bytes(cleanup.freed_bytes || 0)],
    ['保留 import', cleanup.retained_import_dirs || 0],
  ];
  return `<div class="sync-cleanup-list">${rows.map(([label,value]) => `<div class="sync-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
function syncConfigPanel(config){
  const rows = [
    ['Max upload', `${config.max_upload_mb || '-'} MB`],
    ['Skip existing', formatBool(config.skip_existing_uploads)],
    ['Write reports', formatBool(config.write_reports)],
    ['Analyze after import', formatBool(config.analyze_after_import)],
    ['Analyze limit', config.analyze_limit || '-'],
    ['Delete uploads', formatBool(config.delete_uploads_after_import)],
    ['Delete imports', formatBool(config.delete_unreferenced_imports)],
    ['Delete analyzed audio', formatBool(config.delete_audio_after_analysis)],
  ];
  return `<div class="sync-config-list">${rows.map(([label,value]) => `<div class="sync-row"><span>${esc(label)}</span><span class="queue-value">${esc(value)}</span></div>`).join('')}</div>`;
}
async function privacyCenter(){
  const buttons = `<button class="btn" onclick="action('retention',{date:'today'})">保留预览</button><button class="btn danger" onclick="askConfirm('按保留策略删除旧记录、旧运行日志和旧详细报告？') && action('retention',{date:'today',apply:true})">执行保留</button><button class="btn primary" onclick="privacyCenter()">刷新</button>`;
  setHeader('隐私与保留','读取中...', buttons);
  const j = await api('/api/privacy');
  const summary = j.summary || {};
  const sources = j.sources || [];
  const filteredSources = filterPrivacySources(sources);
  const retention = j.retention || {};
  const cleanup = j.cleanup || {};
  $('subtitle').textContent = `${j.generated_at || ''} · ${summary.high_sensitivity_enabled || 0} high sources · ${summary.retention_candidate_rows || 0} retention rows`;
  $('view').innerHTML = `
    <div class="privacy-hero">
      <section class="card">
        <div class="section-title"><h3>隐私概览</h3><span class="muted">${esc(summary.local_only ? 'local-first' : 'external provider')}</span></div>
        <div class="privacy-kpis">
          ${privacyKpi('本地记录', summary.total_records || 0, 'observations / runs / feedback')}
          ${privacyKpi('高敏开启', summary.high_sensitivity_enabled || 0, 'messages / mail / browser / audio')}
          ${privacyKpi('保留候选', summary.retention_candidate_rows || 0, 'dry-run rows')}
          ${privacyKpi('可清缓存', bytes(summary.cleanup_candidate_bytes || 0), 'mobile + recycle')}
        </div>
        <div class="privacy-toolbar">${privacyFilterPills(sources)}</div>
      </section>
      <section class="card">
        <div class="section-title"><h3>快速控制</h3><span class="muted">${esc((j.checks || []).filter(row => row.status !== 'ok').length)} warnings</span></div>
        <div class="overview-actions">
          <button class="btn" onclick="privacyQuickRetention(30)">30 天保留</button>
          <button class="btn" onclick="privacyQuickRetention(90)">90 天保留</button>
          <button class="btn" onclick="privacyQuickRetention(180)">180 天保留</button>
          <button class="btn" onclick="go('setup')">同步 token</button>
          <button class="btn" onclick="go('recycle')">回收箱</button>
          <button class="btn" onclick="go('sources')">来源详情</button>
        </div>
        ${privacyCheckList((j.checks || []).slice(0, 4))}
      </section>
    </div>
    <div class="privacy-main">
      <div style="display:grid;gap:14px;min-width:0">
        <section class="card">
          <div class="section-title"><h3>敏感来源</h3><span class="muted">${esc(filteredSources.length)} shown</span></div>
          ${privacySourceList(filteredSources)}
        </section>
        <section class="card">
          <div class="section-title"><h3>保留策略</h3><span class="muted">dry-run</span></div>
          ${privacyRetentionPanel(retention)}
        </section>
      </div>
      <aside style="display:grid;gap:14px;min-width:0">
        <section class="card">
          <div class="section-title"><h3>清理预览</h3><span class="muted">${esc(bytes(summary.cleanup_candidate_bytes || 0))}</span></div>
          ${privacyCleanupPanel(cleanup)}
        </section>
        <section class="card">
          <div class="section-title"><h3>发布边界</h3><span class="muted">git</span></div>
          ${privacyPublicationPanel(j.publication || {})}
        </section>
        <section class="card">
          <div class="section-title"><h3>数据占用</h3><span class="muted">${esc(bytes(((j.storage || {}).database || {}).size || 0))}</span></div>
          ${privacyStoragePanel(j.storage || {})}
        </section>
      </aside>
    </div>`;
}
function privacyKpi(label, value, hint){
  return `<div class="privacy-kpi"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function privacyFilterPills(rows){
  const counts = {
    all: (rows || []).length,
    high: (rows || []).filter(row => row.sensitivity === 'high').length,
    enabled: (rows || []).filter(row => row.enabled).length,
    text: (rows || []).filter(row => row.retains_text).length,
    disabled: (rows || []).filter(row => !row.enabled).length,
  };
  const filters = [['all','全部'], ['high','高敏'], ['enabled','开启'], ['text','保留文本'], ['disabled','已关闭']];
  return filters.map(([key,label]) => `<button class="filter-pill ${state.privacyView===key?'active':''}" onclick="setPrivacyView('${key}')">${esc(label)} <span class="chip-count">${esc(counts[key] || 0)}</span></button>`).join('');
}
function setPrivacyView(value){
  state.privacyView = value || 'all';
  privacyCenter();
}
function filterPrivacySources(rows){
  const view = state.privacyView || 'all';
  return (rows || []).filter(row => {
    if(view === 'high') return row.sensitivity === 'high';
    if(view === 'enabled') return row.enabled;
    if(view === 'text') return row.retains_text;
    if(view === 'disabled') return !row.enabled;
    return true;
  });
}
function privacySourceList(rows){
  if(!(rows || []).length) return '<div class="empty-state">当前筛选没有来源</div>';
  return `<div class="privacy-source-list">${rows.map(privacySourceCard).join('')}</div>`;
}
function privacySourceCard(row){
  const toggle = row.setting ? `<button class="btn ${row.enabled?'danger':''}" data-setting="${escAttr(row.setting)}" data-value="${row.enabled ? 'false' : 'true'}" onclick="privacySetBool(this)">${row.enabled ? '关闭采集' : '开启采集'}</button>` : `<button class="btn" onclick="go('sync')">查看来源</button>`;
  return `<article class="privacy-source-card ${esc(row.sensitivity || 'medium')} ${row.enabled?'':'disabled'}">
    <div class="privacy-row-head">
      <div>
        <div class="privacy-title">${esc(row.label || row.id)}</div>
        <div class="item-meta">${esc(row.source || '')}/${esc(row.kind || '')} · ${esc(row.setting || 'runtime source')}</div>
      </div>
      <div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">${status(row.enabled ? 'on' : 'off')}${status(row.risk || row.sensitivity)}</div>
    </div>
    <div class="privacy-note">${esc(row.note || '')}</div>
    <div class="project-keywords">
      <span class="evidence-chip">${esc(row.count || 0)} records</span>
      <span class="evidence-chip">${esc(row.body_rows || 0)} body rows</span>
      <span class="evidence-chip">${esc(shortDateTime(row.last || '') || 'no latest')}</span>
    </div>
    <div class="privacy-actions">${toggle}<button class="btn" data-source="${escAttr(row.source || '')}" onclick="privacyOpenSource(this)">查来源</button></div>
  </article>`;
}
function privacyOpenSource(button){
  state.sourceView = privacySourceView(button.dataset.source || '');
  go('sources');
}
function privacySourceView(source){
  if(['messages','apple_mail'].includes(source)) return 'chat';
  if(['mobile'].includes(source)) return 'device';
  if(['calendar','reminders','browser','filesystem'].includes(source)) return 'local';
  if(['local_ai','openai'].includes(source)) return 'ai';
  return 'all';
}
async function privacySetBool(button){
  const key = button.dataset.setting || '';
  const value = button.dataset.value === 'true';
  if(!key) return;
  const j = await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({updates:[{key,value}]})});
  toast(`OK privacy setting\n${j.changed_count || 0} changed`);
  privacyCenter();
}
async function privacyQuickRetention(days){
  const value = Number(days || 180);
  const updates = [
    {key:'retention.raw_observations_days', value},
    {key:'retention.activity_samples_days', value},
    {key:'retention.detailed_reports_days', value},
    {key:'retention.collector_runs_days', value},
  ];
  const j = await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({updates})});
  toast(`OK retention\n${j.changed_count || 0} changed`);
  privacyCenter();
}
function privacyRetentionPanel(retention){
  const config = retention.config || {};
  const preview = retention.preview || {};
  const rows = [
    ['原始事件', 'retention.raw_observations_days', config.raw_observations_days ?? 180, `${preview.deleted_observations || 0} before ${preview.observation_cutoff || '-'}`],
    ['App 样本', 'retention.activity_samples_days', config.activity_samples_days ?? 180, `${preview.deleted_activity_samples || 0} before ${preview.activity_cutoff || '-'}`],
    ['详细报告', 'retention.detailed_reports_days', config.detailed_reports_days ?? 180, `${preview.deleted_reports || 0} before ${preview.reports_cutoff || '-'}`],
    ['运行记录', 'retention.collector_runs_days', config.collector_runs_days ?? 45, `${preview.deleted_collector_runs || 0} before ${preview.collector_runs_cutoff || '-'}`],
  ];
  return `<div class="settings-edit-list">
    ${rows.map(([label,key,value,hint]) => `<label class="settings-edit-row"><div class="settings-edit-label"><b>${esc(label)}</b><span>${esc(hint)}</span></div><div class="settings-edit-control"><input data-privacy-retention="${escAttr(key)}" type="number" min="1" max="3650" step="1" value="${escAttr(value)}"></div></label>`).join('')}
    <div class="settings-edit-actions">
      <button class="btn primary" onclick="savePrivacyRetention()">保存保留策略</button>
      <button class="btn" onclick="action('retention',{date:'today'})">重新预览</button>
      <button class="btn danger" onclick="askConfirm('按当前保留策略执行删除？') && action('retention',{date:'today',apply:true})">执行清理</button>
    </div>
    <details class="settings-json">
      <summary>查看 dry-run 输出</summary>
      <pre class="settings-pre">${esc((preview.lines || []).join('\\n') || 'No retention preview')}</pre>
    </details>
  </div>`;
}
async function savePrivacyRetention(){
  const updates = Array.from(document.querySelectorAll('[data-privacy-retention]')).map(input => ({key: input.dataset.privacyRetention, value: input.value}));
  const j = await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({updates})});
  toast(`OK retention\n${j.changed_count || 0} changed`);
  privacyCenter();
}
function privacyCleanupPanel(cleanup){
  const mobile = cleanup.mobile || {};
  const recycle = cleanup.recycle || {};
  const recycleSummary = recycle.summary || {};
  const rows = [
    ['移动缓存文件', mobile.deleted_files || 0, bytes(mobile.freed_bytes || 0)],
    ['移动导入目录', mobile.deleted_dirs || 0, `${mobile.retained_import_dirs || 0} retained`],
    ['回收箱条目', recycleSummary.files || 0, bytes(recycleSummary.total_bytes || 0)],
    ['到期回收文件', recycle.deleted_files || 0, bytes(recycle.freed_bytes || 0)],
  ];
  return `<div class="maintenance-list">
    ${rows.map(([label,value,hint]) => maintenanceLine(label, value, hint)).join('')}
    <div class="privacy-actions">
      <button class="btn" onclick="action('mobile_cleanup',{})">缓存预览</button>
      <button class="btn danger" onclick="askConfirm('执行移动端缓存清理？') && action('mobile_cleanup',{apply:true})">执行缓存清理</button>
      <button class="btn" onclick="action('recycle_purge',{})">回收箱预览</button>
      <button class="btn danger" onclick="askConfirm('永久删除已到期的回收箱文件？') && action('recycle_purge',{apply:true})">清理回收箱</button>
    </div>
  </div>`;
}
function privacyCheckList(rows){
  if(!(rows || []).length) return '<div class="empty-state">没有检查项</div>';
  return `<div class="privacy-check-list">${rows.map(row => `<div class="privacy-check-row"><div><div class="privacy-title">${esc(row.title || row.id)}</div><div class="privacy-note">${esc(row.detail || '')}</div>${row.action?`<div class="item-meta">${esc(row.action)}</div>`:''}</div>${status(row.status || 'info')}</div>`).join('')}</div>`;
}
function privacyPublicationPanel(publication){
  const tracked = publication.tracked_private_files || [];
  const patterns = publication.ignored_patterns || [];
  return `<div class="maintenance-list">
    ${maintenanceLine('Gitignore', publication.gitignore_exists ? 'present' : 'missing', shortPath(publication.gitignore_path || ''))}
    ${maintenanceLine('Tracked private', tracked.length, tracked.slice(0, 3).join(', ') || 'none')}
    <div class="privacy-check-list">
      ${patterns.map(item => `<div class="privacy-check-row"><div><div class="privacy-title">${esc(item.pattern)}</div><div class="privacy-note">${esc(item.present ? 'covered by .gitignore' : 'not found in .gitignore')}</div></div>${status(item.present ? 'ok' : 'warn')}</div>`).join('')}
    </div>
  </div>`;
}
function privacyStoragePanel(storage){
  const db = storage.database || {};
  const dirs = storage.directories || [];
  const tables = storage.tables || {};
  const topDirs = dirs.slice().sort((a,b) => Number(b.size || 0) - Number(a.size || 0)).slice(0, 8);
  const tableRows = Object.entries(tables).filter(([,value]) => Number(value || 0) > 0).slice(0, 8);
  return `<div>
    <div class="privacy-storage-list">
      <div class="privacy-storage-row"><div><div class="privacy-title">SQLite</div><div class="privacy-note">${esc(shortPath(db.path || ''))}</div></div><div class="queue-value">${esc(bytes(db.size || 0))}</div></div>
      ${topDirs.map(dir => `<div class="privacy-storage-row"><div><div class="privacy-title">${esc(dir.name || '-')}</div><div class="privacy-note">${esc(shortPath(dir.path || ''))}</div></div><div class="queue-value">${esc(bytes(dir.size || 0))}</div></div>`).join('')}
    </div>
    <div class="settings-chip-row" style="margin-top:10px">${tableRows.map(([key,value]) => `<span class="settings-chip">${esc(key)}: ${esc(value)}</span>`).join('') || '<span class="settings-chip">no table rows</span>'}</div>
  </div>`;
}
async function maintenance(){
  const buttons = `<button class="btn" onclick="action('retention',{date:'today'})">记录预览</button><button class="btn danger" onclick="askConfirm('按保留策略删除旧记录、旧运行日志和旧详细报告？') && action('retention',{date:'today',apply:true})">执行记录清理</button><button class="btn" onclick="action('mobile_cleanup',{})">缓存预览</button><button class="btn" onclick="action('recycle_purge',{})">回收箱预览</button><button class="btn primary" onclick="maintenance()">刷新</button>`;
  setHeader('记录维护','读取中...', buttons);
  const j=await api('/api/maintenance');
  const counts = j.counts || {};
  const retention = j.retention_preview || {};
  const mobile = j.mobile_cleanup_preview || {};
  const recycle = j.recycle_purge_preview || {};
  const logs = j.log_files || {};
  const db = j.database || {};
  const recordRows = Number(retention.deleted_observations || 0) + Number(retention.deleted_activity_samples || 0) + Number(retention.deleted_collector_runs || 0);
  const reclaimBytes = Number(mobile.freed_bytes || 0) + Number(recycle.freed_bytes || 0);
  $('subtitle').textContent = `${j.generated_at || ''} · preview ${recordRows} records · ${bytes(reclaimBytes)} cache/recycle`;
  $('view').innerHTML = `
    <div class="maintenance-hero">
      <section class="card">
        <div class="section-title"><h3>记录体量</h3><span class="muted">${esc(shortPath(db.path || ''))}</span></div>
        <div class="maintenance-kpis">
          ${maintenanceKpi('Observations', counts.observations || 0, '今天/时间线/来源/搜索')}
          ${maintenanceKpi('Activity samples', counts.activity_samples || 0, 'foreground app samples')}
          ${maintenanceKpi('Collector runs', counts.collector_runs || 0, '运行记录')}
          ${maintenanceKpi('Log files', logs.count || 0, bytes(logs.total_size || 0))}
        </div>
      </section>
      <section class="card">
        <div class="section-title"><h3>清理动作</h3><span class="muted">先预览，再执行</span></div>
        <div class="maintenance-action-grid">
          <button class="btn" onclick="action('retention',{date:'today'})">记录预览</button>
          <button class="btn danger" onclick="askConfirm('按保留策略删除旧记录、旧运行日志和旧详细报告？') && action('retention',{date:'today',apply:true})">执行记录清理</button>
          <button class="btn" onclick="action('mobile_cleanup',{})">缓存预览</button>
          <button class="btn danger" onclick="askConfirm('执行移动端缓存清理？') && action('mobile_cleanup',{apply:true})">执行缓存清理</button>
          <button class="btn" onclick="action('recycle_purge',{})">回收箱预览</button>
          <button class="btn danger" onclick="askConfirm('永久删除已到期的回收箱文件？') && action('recycle_purge',{apply:true})">清理回收箱</button>
        </div>
      </section>
    </div>
    <div class="maintenance-main">
      <div class="grid">
        <section class="card">
          <div class="section-title"><h3>按保留策略清理记录</h3><span class="muted">${esc(maintenanceRetentionMode(j.retention))}</span></div>
          ${maintenanceRetentionPanel(retention)}
        </section>
        <section class="card">
          <div class="section-title"><h3>缓存与回收箱</h3><span class="muted">${esc(bytes(reclaimBytes))}</span></div>
          ${maintenanceCachePanel(mobile, recycle)}
        </section>
        <section class="card">
          <div class="section-title"><h3>增长来源</h3><span class="muted">top source/kind</span></div>
          ${maintenanceSourcePanel(j.source_counts || [])}
        </section>
      </div>
      <div class="maintenance-side">
        <section class="card">
          <div class="section-title"><h3>数据库</h3><span class="muted">${esc(bytes(db.size || 0))}</span></div>
          ${maintenanceDbPanel(db, counts)}
        </section>
        <section class="card">
          <div class="section-title"><h3>日志文件</h3><span class="muted">${esc(bytes(logs.total_size || 0))}</span></div>
          ${maintenanceLogPanel(logs)}
        </section>
      </div>
    </div>`;
}
function maintenanceKpi(label, value, hint){
  const compact = String(value ?? '').length > 10;
  return `<div class="maintenance-kpi"><div class="label">${esc(label)}</div><div class="value ${compact?'compact':''}">${esc(value)}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function maintenanceRetentionMode(config){
  if(!config) return 'retention';
  return `raw ${config.raw_observations_days || '-'}d / runs ${config.collector_runs_days || '-'}d`;
}
function maintenanceRetentionPanel(preview){
  const rows = [
    ['Raw observations', preview.deleted_observations || 0, `before ${preview.observation_cutoff || '-'}`],
    ['Activity samples', preview.deleted_activity_samples || 0, `before ${preview.activity_cutoff || '-'}`],
    ['Collector runs', preview.deleted_collector_runs || 0, `before ${preview.collector_runs_cutoff || '-'}`],
    ['Detailed reports', preview.deleted_reports || 0, `before ${preview.reports_cutoff || '-'}`],
    ['Trimmed logs', preview.trimmed_logs || 0, 'oversized .log files'],
  ];
  const skipped = (preview.skipped_days || []).length;
  return `<div class="maintenance-list">
    ${rows.map(([label,value,hint]) => maintenanceLine(label, value, hint)).join('')}
    ${skipped ? maintenanceLine('Skipped days', skipped, 'missing daily summaries') : ''}
    <details class="settings-json">
      <summary>查看 retention dry-run 输出</summary>
      <pre class="settings-pre">${esc((preview.lines || []).join('\\n') || 'No retention preview')}</pre>
    </details>
  </div>`;
}
function maintenanceCachePanel(mobile, recycle){
  const rows = [
    ['Mobile cached files', mobile.deleted_files || 0, bytes(mobile.freed_bytes || 0)],
    ['Mobile import dirs', mobile.deleted_dirs || 0, `${mobile.retained_import_dirs || 0} retained`],
    ['Recycle files due', recycle.deleted_files || 0, bytes(recycle.freed_bytes || 0)],
    ['Recycle manifests', recycle.deleted_manifests || 0, `${recycle.deleted_dirs || 0} empty dirs`],
  ];
  return `<div class="maintenance-list">${rows.map(([label,value,hint]) => maintenanceLine(label, value, hint)).join('')}</div>`;
}
function maintenanceDbPanel(db, counts){
  const rows = [
    ['Path', shortPath(db.path || '-')],
    ['Size', bytes(db.size || 0)],
    ['Modified', shortDateTime(db.modified_at || '-')],
    ['Total rows', Number(counts.observations || 0) + Number(counts.activity_samples || 0) + Number(counts.collector_runs || 0)],
  ];
  return `<div class="maintenance-list">${rows.map(([label,value]) => maintenanceLine(label, value)).join('')}</div>`;
}
function maintenanceSourcePanel(rows){
  if(!(rows || []).length) return '<div class="empty-state">No source records</div>';
  return `<div class="maintenance-source-list">${rows.slice(0, 16).map(row => `<div class="maintenance-source-row"><div class="maintenance-source-title">${esc(row.source || '-')}/${esc(row.kind || '-')}</div><div class="item-meta">${esc(row.first || '-')} -> ${esc(row.last || '-')}</div><div class="queue-value">${esc(row.count || 0)}</div></div>`).join('')}</div>`;
}
function maintenanceLogPanel(logs){
  const files = logs.files || [];
  if(!files.length) return '<div class="empty-state">No log files</div>';
  return `<div class="maintenance-log-list">${files.map(file => `<div class="maintenance-log-row"><div class="maintenance-log-title">${esc(shortPath(file.path || '-'))}</div><div class="item-meta">${esc(shortDateTime(file.modified_at || '-'))}</div><div class="queue-value">${esc(bytes(file.size || 0))}</div></div>`).join('')}</div>`;
}
function maintenanceLine(label, value, hint=''){
  return `<div class="maintenance-line"><span>${esc(label)}</span><span><b>${esc(value)}</b>${hint?`<br><span class="muted">${esc(hint)}</span>`:''}</span></div>`;
}
async function settings(){
  const buttons = `<button class="btn primary" onclick="settings()">刷新</button>`;
  setHeader('配置','读取中...', buttons);
  const j=await api('/api/settings');
  const cfg = j.settings || {};
  const editable = j.editable || [];
  const groups = settingsGroups(cfg);
  if(!groups.some(group => group.key === state.settingsGroup)) state.settingsGroup = groups[0]?.key || '';
  const selected = groups.find(group => group.key === state.settingsGroup) || groups[0];
  const shown = filterSettingsGroups(groups);
  const collectors = cfg.collectors || {};
  const collectorTotal = Object.keys(collectors).length;
  const collectorEnabled = Object.values(collectors).filter(Boolean).length;
  const provider = (cfg.ai_backend || {}).provider || 'local';
  const localAi = cfg.local_ai || {};
  const mobile = cfg.mobile_sync || {};
  const file = cfg.file_analysis || {};
  const audio = cfg.audio_analysis || {};
  const watchPaths = Array.isArray(cfg.watch_paths) ? cfg.watch_paths : [];
  setHeader('配置',`${editable.length} 项可直接调整；敏感字段已隐藏`, buttons);
  $('view').innerHTML = `
    <div class="settings-hero">
      <section class="card">
        <div class="section-title"><h3>配置总览</h3><span class="muted">${esc(shortPath(j.config_path || ''))}</span></div>
        <div class="settings-kpis">
          ${settingsKpi('采集器', `${collectorEnabled}/${collectorTotal || 0}`, '当前开启数量')}
          ${settingsKpi('AI provider', String(provider).toUpperCase(), localAi.text_model || localAi.model || '-')}
          ${settingsKpi('移动同步', mobile.enabled === false ? '关闭' : '开启', mobile.port ? `port ${mobile.port}` : '-')}
          ${settingsKpi('监控路径', watchPaths.length, watchPaths.map(shortPath).join(' / ') || '-')}
        </div>
        <div class="settings-chip-row">
          <span class="settings-chip">时区 ${esc(cfg.timezone || '-')}</span>
          <span class="settings-chip">文件分析 ${esc(formatBool(file.enabled !== false))}</span>
          <span class="settings-chip">分析后删除 ${esc(formatBool(file.delete_after_analysis))}</span>
          <span class="settings-chip">音频连续队列 ${esc(formatBool(audio.continuous_queue))}</span>
          <span class="settings-chip">Token ${esc(mobile.token || '-')}</span>
        </div>
      </section>
      <div class="settings-side">
        ${settingsLanguagePanel()}
        ${settingsMaintenancePanel(cfg)}
      </div>
    </div>
    <div class="settings-main">
      <section class="card">
        <div class="section-title"><h3>配置分组</h3><span id="settingsShownCount" class="muted">${shown.length} / ${groups.length} 组</span></div>
        <div class="settings-toolbar">
          <input id="settingsSearch" value="${escAttr(state.settingsQ)}" oninput="applySettingsSearch(this.value)" placeholder="筛选分组、字段或值">
          <button class="btn" onclick="state.settingsQ=''; settings()">All</button>
        </div>
        <div class="settings-group-grid">${settingsGroupGrid(groups)}</div>
        <div id="settingsEmpty" class="empty-state" style="${shown.length ? 'display:none' : ''}">没有匹配的配置分组</div>
      </section>
      <div class="settings-side">
        <section class="card">${settingsEditPanel(selected, cfg, editable)}</section>
        <details class="card compact-details">
          <summary>当前分组详情</summary>
          <div class="compact-details-body">${settingsDetailPanel(selected)}</div>
        </details>
        <details class="card compact-details">
          <summary>路径和安全</summary>
          <div class="compact-details-body">${settingsPathPanel(j, cfg)}</div>
        </details>
      </div>
    </div>`;
  applySettingsSearch(state.settingsQ);
}
function settingsKpi(label, value, hint){
  const compact = String(value ?? '').length > 12 ? ' compact' : '';
  return `<div class="settings-kpi"><div class="label">${esc(label)}</div><div class="value${compact}">${esc(value ?? '-')}</div><div class="hint">${esc(hint || '')}</div></div>`;
}
function settingsLanguagePanel(){
  return `<section class="card">
    <div class="section-title"><h3>语言设置</h3><span class="muted">${esc(supportedLanguages.find(([code]) => code === currentLanguage())?.[1] || 'English')}</span></div>
    <label class="settings-edit-row" style="grid-template-columns: 112px minmax(0, 1fr); border-bottom:0; padding:0">
      <div class="settings-edit-label"><b>界面语言</b><span>选择界面语言</span></div>
      <div class="settings-edit-control">
        <select id="dashboardLanguage" onchange="setLanguage(this.value)" aria-label="Interface language">${languageOptions()}</select>
      </div>
    </label>
    <div class="settings-edit-note">切换会保存在此浏览器，并同步为日报/周报邮件语言。</div>
  </section>`;
}
function settingsEditPanel(group, cfg, editable){
  if(!group) return '<div class="empty-state">No settings selected</div>';
  const fields = settingsEditableForGroup(group.key, editable);
  if(!fields.length){
    return `<div>
      <div class="section-title"><h3>可编辑设置</h3><span class="status disabled">只读</span></div>
      <div class="empty-state">这个分组暂时没有开放直接编辑。敏感字段和高风险命令类配置仍保留为只读。</div>
    </div>`;
  }
  return `<form id="settingsEditForm" onsubmit="saveSettingsGroup(event, '${escAttr(group.key)}')">
    <div class="section-title"><h3>可编辑设置</h3><span class="status ok">${esc(fields.length)} 项</span></div>
    <div class="settings-edit-list">${fields.map(field => settingsEditRow(field, cfg)).join('')}</div>
    <div class="settings-edit-actions">
      <button class="btn primary" type="submit">保存设置</button>
      <button class="btn" type="button" onclick="action('install_agent',{load:true})">重载 Agent</button>
      <button class="btn" type="button" onclick="action('install_sync_agent',{load:true})">重载同步服务</button>
      <button class="btn" type="button" onclick="action('install_dashboard_agent',{load:true})">重载 Dashboard</button>
    </div>
    <div class="settings-edit-note">保存会立即写入 config.json；后台采集或同步进程通常需要重载后才会使用新配置。</div>
  </form>`;
}
function settingsEditableForGroup(key, editable){
  return (editable || []).filter(field => field.group === key || field.key === key);
}
function settingsEditRow(field, cfg){
  const value = settingValueAt(cfg, field.path || []);
  const meta = settingsFieldMeta(field);
  return `<label class="settings-edit-row">
    <div class="settings-edit-label"><b>${esc(field.label || field.key)}</b><span>${esc(meta || field.key)}</span></div>
    <div class="settings-edit-control">${settingsEditControl(field, value)}</div>
  </label>`;
}
function settingsEditControl(field, value){
  const key = escAttr(field.key);
  const type = escAttr(field.type);
  const base = `data-setting-key="${key}" data-setting-type="${type}"`;
  const placeholder = field.placeholder ? ` placeholder="${escAttr(field.placeholder)}"` : '';
  if(field.type === 'bool'){
    return `<span class="settings-edit-toggle"><input ${base} type="checkbox" ${value ? 'checked' : ''}>${esc(value ? '开启' : '关闭')}</span>`;
  }
  if(field.type === 'choice'){
    const options = (field.options || []).map(option => `<option value="${escAttr(option)}" ${String(value ?? '')===String(option)?'selected':''}>${esc(option)}</option>`).join('');
    return `<select ${base}>${options}</select>`;
  }
  if(field.type === 'list_string'){
    const text = Array.isArray(value) ? value.join('\n') : String(value ?? '');
    const rows = Number(field.rows || 4);
    return `<textarea ${base} rows="${escAttr(rows)}"${placeholder}>${esc(text)}</textarea>`;
  }
  if(field.type === 'text'){
    const rows = Number(field.rows || 4);
    return `<textarea ${base} rows="${escAttr(rows)}"${placeholder}>${esc(value ?? '')}</textarea>`;
  }
  if(field.type === 'int' || field.type === 'float'){
    const step = field.type === 'int' ? '1' : 'any';
    const min = field.min !== undefined ? ` min="${escAttr(field.min)}"` : '';
    const max = field.max !== undefined ? ` max="${escAttr(field.max)}"` : '';
    return `<input ${base} type="number" step="${step}" value="${escAttr(value ?? '')}"${min}${max}${placeholder}>`;
  }
  return `<input ${base} value="${escAttr(value ?? '')}"${placeholder}>`;
}
function settingsFieldMeta(field){
  const parts = [field.key];
  if(field.min !== undefined || field.max !== undefined){
    const range = `${field.min !== undefined ? field.min : '-'}..${field.max !== undefined ? field.max : '-'}`;
    parts.push(range);
  }
  if(field.unit) parts.push(field.unit);
  return parts.join(' · ');
}
function settingValueAt(cfg, path){
  let current = cfg;
  for(const part of (path || [])){
    if(!current || typeof current !== 'object') return '';
    current = current[part];
  }
  return current;
}
async function saveSettingsGroup(event, groupKey){
  event.preventDefault();
  const form = event.currentTarget;
  const controls = Array.from(form.querySelectorAll('[data-setting-key]'));
  const updates = controls.map(control => ({key: control.dataset.settingKey, value: settingControlValue(control)}));
  const j = await api('/api/settings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({updates})});
  toast(`OK settings\n${j.changed_count || 0} changed`);
  settings().catch(e => toast(String(e)));
}
function settingControlValue(control){
  if(control.dataset.settingType === 'bool') return control.checked;
  if(control.dataset.settingType === 'list_string') return control.value.split('\n').map(item => item.trim()).filter(Boolean);
  return control.value;
}
function settingsMaintenancePanel(cfg){
  const retention = cfg.retention || {};
  const recycle = cfg.recycle_bin || {};
  const mobile = cfg.mobile_sync || {};
  const rows = [
    ['长期保留', retention.enabled === false ? '关闭' : '按配置启用'],
    ['回收箱', recycle.enabled === false ? '关闭' : `保留 ${recycle.retention_hours || 24}h`],
    ['同步上传上限', mobile.max_upload_mb ? `${mobile.max_upload_mb} MB` : '-'],
    ['同步清理', formatBool(mobile.delete_unreferenced_imports)],
  ];
  return `<details class="card compact-details">
    <summary>维护动作</summary>
    <div class="compact-details-body">
    <div class="settings-action-grid">
      <button class="btn" onclick="action('retention',{date:'today'})">保留预览</button>
      <button class="btn danger" onclick="askConfirm('执行长期保留清理？') && action('retention',{date:'today',apply:true})">执行保留</button>
      <button class="btn" onclick="go('files')">文件</button>
      <button class="btn" onclick="go('sync')">手机同步</button>
      <button class="btn" onclick="go('maintenance')">记录维护</button>
      <button class="btn" onclick="go('recycle')">回收箱</button>
    </div>
    <div class="settings-row-list" style="margin-top:10px">${rows.map(([label,value]) => `<div class="settings-row"><div class="label">${esc(label)}</div><div class="value">${esc(value)}</div></div>`).join('')}</div>
    </div>
  </details>`;
}
function settingsGroups(cfg){
  const groups = [];
  const dashboard = cfg.dashboard || {};
  const dashboardLang = normalizeLanguage(dashboard.language || activeLanguage);
  groups.push(settingsGroup('dashboard', dashboard, {
    label: 'Dashboard',
    status: supportedLanguages.find(([code]) => code === dashboardLang)?.[1] || dashboardLang,
    statusClass: 'info',
    summary: '界面语言，也会作为日报和周报邮件的输出语言。',
    items: [['language', dashboardLang]],
  }));
  const collectors = cfg.collectors || {};
  const collectorEntries = Object.entries(collectors);
  const collectorEnabled = collectorEntries.filter(([,enabled]) => !!enabled).length;
  const collectorOff = collectorEntries.filter(([,enabled]) => !enabled).map(([key]) => key);
  groups.push(settingsGroup('collectors', collectors, {
    label: '采集器',
    status: `${collectorEnabled}/${collectorEntries.length || 0} 开启`,
    statusClass: collectorEnabled ? 'ok' : 'warn',
    tone: collectorEnabled ? 'ok' : 'warn',
    summary: 'Mac 端数据来源开关，决定后台会采集哪些本机信号。',
    items: [['开启', `${collectorEnabled}/${collectorEntries.length || 0}`], ['关闭', collectorOff.join(', ') || '-']],
  }));
  groups.push(settingsGroup('ai_backend', cfg.ai_backend || {}, {
    label: 'AI 路由',
    status: (cfg.ai_backend || {}).provider || 'local',
    statusClass: 'info',
    summary: '决定分析和问答优先走本地模型还是外部 provider。',
    items: [['provider', (cfg.ai_backend || {}).provider || '-'], ['fallback', (cfg.ai_backend || {}).fallback_provider || '-']],
  }));
  groups.push(settingsGroup('local_ai', cfg.local_ai || {}, {
    label: '本地 AI',
    status: (cfg.ai_backend || {}).provider === 'local' ? '使用中' : '备用',
    statusClass: (cfg.ai_backend || {}).provider === 'local' ? 'ok' : 'info',
    tone: (cfg.ai_backend || {}).provider === 'local' ? 'ok' : '',
    summary: 'Ollama、转写后端和本地模型配置。',
    items: [['text_model', (cfg.local_ai || {}).text_model || '-'], ['vision_model', (cfg.local_ai || {}).vision_model || '-'], ['transcription', (cfg.local_ai || {}).transcription_backend || '-']],
  }));
  groups.push(settingsGroup('openai_analysis', cfg.openai_analysis || {}, {
    label: 'OpenAI 备用',
    status: (cfg.openai_analysis || {}).enabled ? '开启' : '关闭',
    statusClass: (cfg.openai_analysis || {}).enabled ? 'ok' : 'disabled',
    tone: (cfg.openai_analysis || {}).enabled ? 'ok' : 'disabled',
    summary: '外部 OpenAI 分析配置；敏感字段在这里不会明文显示。',
  }));
  groups.push(settingsGroup('audio_analysis', cfg.audio_analysis || {}, {
    label: '音频分析',
    status: (cfg.audio_analysis || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.audio_analysis || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.audio_analysis || {}).enabled === false ? 'disabled' : 'ok',
    summary: '移动录音转写、摘要、队列处理和音频清理策略。',
    items: [['continuous_queue', formatBool((cfg.audio_analysis || {}).continuous_queue)], ['summary_model', (cfg.audio_analysis || {}).summary_model || '-'], ['auto_limit', (cfg.audio_analysis || {}).auto_limit ?? '-']],
  }));
  groups.push(settingsGroup('audio_preprocessing', cfg.audio_preprocessing || {}, {
    label: '音频预处理',
    status: (cfg.audio_preprocessing || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.audio_preprocessing || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.audio_preprocessing || {}).enabled === false ? 'disabled' : 'ok',
    summary: 'ASR/diarization 前的人声增强、speaker sample 增强和重叠说话候选分离。',
    items: [['ASR', formatBool((cfg.audio_preprocessing || {}).asr_enabled)], ['Diarization', formatBool((cfg.audio_preprocessing || {}).diarization_enabled)], ['Overlap', (cfg.audio_preprocessing || {}).overlap_separation_backend || '-']],
  }));
  groups.push(settingsGroup('speaker_recognition', cfg.speaker_recognition || {}, {
    label: '说话人',
    status: (cfg.speaker_recognition || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.speaker_recognition || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.speaker_recognition || {}).enabled === false ? 'disabled' : 'ok',
    summary: '说话人聚类、样本和后续重命名合并的识别参数。',
  }));
  groups.push(settingsGroup('mobile_sync', cfg.mobile_sync || {}, {
    label: '手机同步',
    status: (cfg.mobile_sync || {}).enabled === false ? '关闭' : `port ${(cfg.mobile_sync || {}).port || '-'}`,
    statusClass: (cfg.mobile_sync || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.mobile_sync || {}).enabled === false ? 'disabled' : 'ok',
    summary: 'iPhone / Watch 上传入口、去重、导入后分析和缓存清理。',
    items: [['port', (cfg.mobile_sync || {}).port || '-'], ['token', (cfg.mobile_sync || {}).token || '-'], ['delete_uploads', formatBool((cfg.mobile_sync || {}).delete_uploads_after_import)]],
  }));
  groups.push(settingsGroup('file_analysis', cfg.file_analysis || {}, {
    label: '文件分析',
    status: (cfg.file_analysis || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.file_analysis || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.file_analysis || {}).enabled === false ? 'disabled' : 'ok',
    summary: '监控文件、分析副本、include/exclude 后缀和分析后移动策略。',
    items: [['copy_dir', (cfg.file_analysis || {}).analysis_copy_dir || '-'], ['delete_after_analysis', formatBool((cfg.file_analysis || {}).delete_after_analysis)], ['suffixes', Array.isArray((cfg.file_analysis || {}).include_suffixes) ? `${cfg.file_analysis.include_suffixes.length} 项` : '-']],
  }));
  groups.push(settingsGroup('recycle_bin', cfg.recycle_bin || {}, {
    label: '回收箱',
    status: (cfg.recycle_bin || {}).enabled === false ? '关闭' : '开启',
    statusClass: (cfg.recycle_bin || {}).enabled === false ? 'disabled' : 'ok',
    tone: (cfg.recycle_bin || {}).enabled === false ? 'disabled' : 'ok',
    summary: '分析后暂存文件的保留时间、清理和恢复边界。',
  }));
  groups.push(settingsGroup('retention', cfg.retention || {}, { label: '长期保留', summary: '日报、周报、月报和旧记录清理窗口。' }));
  const personalMemory = cfg.personal_memory || {};
  groups.push(settingsGroup('personal_memory', personalMemory, {
    label: '个人记忆',
    status: personalMemory.enabled === false ? '关闭' : '开启',
    statusClass: personalMemory.enabled === false ? 'disabled' : 'ok',
    tone: personalMemory.enabled === false ? 'disabled' : 'ok',
    summary: '个人档案、候选记忆、确认记忆、Q&A 上下文和高敏确认规则。',
    items: [
      ['候选来源', Array.isArray(personalMemory.candidate_sources) ? personalMemory.candidate_sources.join(', ') : '-'],
      ['Q&A', formatBool(personalMemory.qa_include_confirmed !== false)],
      ['候选上限', personalMemory.max_candidates_per_day || '-'],
    ],
  }));
  const emailReports = cfg.email_reports || {};
  groups.push(settingsGroup('email_reports', emailReports, {
    label: '邮件报告',
    summary: '摘要邮件发送时间、SMTP、Keychain 和日报/周报模型配置。',
    items: [
      ['daily_model', emailReports.daily_model || emailReports.model || '-'],
      ['weekly_model', emailReports.weekly_model || emailReports.model || '-'],
      ['fallback_model', emailReports.fallback_model || '-'],
      ['timeout_s', emailReports.ollama_timeout_seconds || '-'],
      ['ai_highlights', formatBool(emailReports.ai_highlights)],
    ],
  }));
  groups.push(settingsGroup('watch_paths', cfg.watch_paths || [], {
    label: '监控路径',
    status: `${Array.isArray(cfg.watch_paths) ? cfg.watch_paths.length : 0} 条`,
    statusClass: Array.isArray(cfg.watch_paths) && cfg.watch_paths.length ? 'ok' : 'warn',
    tone: Array.isArray(cfg.watch_paths) && cfg.watch_paths.length ? 'ok' : 'warn',
    summary: '文件分析会扫描的桌面端目录。',
  }));
  groups.push(settingsGroup('browser_profiles', cfg.browser_profiles || {}, { label: '浏览器资料', summary: '浏览器历史或书签采集所需的 profile 路径。' }));
  groups.push(settingsGroup('limits', cfg.limits || {}, { label: '限制', summary: '单次采集、分析或导入的安全上限。' }));
  groups.push(settingsGroup('agent', cfg.agent || {}, { label: '后台 Agent', summary: 'LaunchAgent、采集频率和后台运行参数。' }));
  const known = new Set(groups.map(group => group.key));
  Object.keys(cfg || {}).sort().forEach(key => {
    if(!known.has(key)) groups.push(settingsGroup(key, cfg[key]));
  });
  return groups;
}
function settingsGroup(key, value, opts={}){
  return {
    key,
    value,
    label: opts.label || settingsGroupLabel(key),
    summary: opts.summary || settingsValueSummary(value),
    status: opts.status || settingsStatusText(value),
    statusClass: opts.statusClass || settingsStatusClass(value),
    tone: opts.tone ?? settingsTone(value),
    items: opts.items || settingsPreviewItems(value),
  };
}
function settingsGroupGrid(groups){
  const q = String(state.settingsQ || '').trim().toLowerCase();
  return (groups || []).map(group => {
    const hidden = q && !settingsGroupMatches(group, q);
    return `<button type="button" class="settings-group-card ${state.settingsGroup===group.key?'active':''} ${esc(group.tone || '')}" data-search="${escAttr(settingsSearchKey(group))}" ${hidden?'hidden':''} onclick="setSettingsGroup('${escAttr(group.key)}')">
      <div class="settings-group-head"><div class="settings-group-title">${esc(group.label)}</div>${settingsStatusBadge(group)}</div>
      <div class="settings-group-summary">${esc(group.summary || '')}</div>
      ${settingsMiniItems(group.items)}
    </button>`;
  }).join('');
}
function settingsMiniItems(items){
  const shown = (items || []).slice(0, 3);
  if(!shown.length) return '';
  return `<div class="settings-chip-row">${shown.map(([label,value]) => `<span class="settings-chip">${esc(label)}: ${esc(settingsValueShort(value, 34))}</span>`).join('')}</div>`;
}
function settingsStatusBadge(group){
  return `<span class="status ${esc(group.statusClass || 'info')}">${esc(group.status || '配置')}</span>`;
}
function settingsDetailPanel(group){
  if(!group) return '<div class="empty-state">No settings</div>';
  return `<div>
    <div class="section-title"><h3>${esc(group.label)}</h3>${settingsStatusBadge(group)}</div>
    <div class="settings-detail-summary">${esc(group.summary || '')}</div>
    <div class="settings-row-list">${settingsRows(group.value, 16)}</div>
    <details class="settings-json">
      <summary>查看该分组原始 JSON</summary>
      <pre class="settings-pre">${esc(JSON.stringify(group.value, null, 2))}</pre>
    </details>
  </div>`;
}
function settingsPathPanel(j, cfg){
  const file = cfg.file_analysis || {};
  const recycle = cfg.recycle_bin || {};
  const rows = [
    ['配置文件', j.config_path || '-'],
    ['数据目录', j.data_dir || '-'],
    ['监控路径', cfg.watch_paths || []],
    ['分析副本目录', file.analysis_copy_dir || '-'],
    ['回收箱目录', recycle.path || recycle.base_dir || '-'],
    ['脱敏状态', 'secret/token/key 已隐藏或显示为 configured'],
  ];
  return `<div>
    <div class="section-title"><h3>路径和安全</h3><span class="status ok">受控写入</span></div>
    <div class="settings-row-list">${rows.map(([label,value]) => `<div class="settings-row"><div class="label">${esc(label)}</div><div class="value">${settingsDisplayValue(value)}</div></div>`).join('')}</div>
  </div>`;
}
function settingsRows(value, maxRows=14){
  const entries = settingsEntries(value);
  if(!entries.length) return '<div class="empty-state">No settings in this group</div>';
  const shown = entries.slice(0, maxRows).map(([label,item]) => `<div class="settings-row"><div class="label">${esc(label)}</div><div class="value">${settingsDisplayValue(item)}</div></div>`).join('');
  const extra = entries.length > maxRows ? `<div class="settings-row"><div class="label">...</div><div class="value">${esc(entries.length - maxRows)} more fields</div></div>` : '';
  return shown + extra;
}
function settingsEntries(value){
  if(Array.isArray(value)) return value.map((item, index) => [`#${index + 1}`, item]);
  if(value && typeof value === 'object') return Object.entries(value);
  if(value === undefined || value === null || value === '') return [];
  return [['value', value]];
}
function settingsDisplayValue(value){
  if(Array.isArray(value)){
    if(!value.length) return '<span class="muted">-</span>';
    return `<div class="settings-chip-row" style="margin-top:0">${value.slice(0, 12).map(item => `<span class="settings-chip">${esc(settingsValueShort(item, 42))}</span>`).join('')}${value.length > 12 ? `<span class="settings-chip">+${esc(value.length - 12)}</span>` : ''}</div>`;
  }
  if(value && typeof value === 'object') return `<span class="muted">${Object.keys(value).length} fields</span>`;
  if(typeof value === 'boolean') return esc(formatBool(value));
  if(value === undefined || value === null || value === '') return '<span class="muted">-</span>';
  return esc(settingsValueShort(value, 160));
}
function settingsPreviewItems(value){
  return settingsEntries(value).slice(0, 3).map(([label,item]) => [label, settingsValueShort(item, 42)]);
}
function settingsStatusText(value){
  const enabled = settingsEnabled(value);
  if(enabled !== null) return formatBool(enabled);
  if(Array.isArray(value)) return `${value.length} 项`;
  if(value && typeof value === 'object') return `${Object.keys(value).length} 项`;
  if(typeof value === 'boolean') return formatBool(value);
  if(value === undefined || value === null || value === '') return '-';
  return settingsValueShort(value, 24);
}
function settingsStatusClass(value){
  const enabled = settingsEnabled(value);
  if(enabled === true) return 'ok';
  if(enabled === false) return 'disabled';
  if(Array.isArray(value)) return value.length ? 'ok' : 'disabled';
  if(value && typeof value === 'object') return Object.keys(value).length ? 'info' : 'disabled';
  if(typeof value === 'boolean') return value ? 'ok' : 'disabled';
  return value ? 'info' : 'disabled';
}
function settingsTone(value){
  const cls = settingsStatusClass(value);
  return cls === 'ok' || cls === 'warn' || cls === 'disabled' ? cls : '';
}
function settingsEnabled(value){
  if(value && typeof value === 'object' && !Array.isArray(value) && Object.prototype.hasOwnProperty.call(value, 'enabled')) return !!value.enabled;
  return null;
}
function settingsValueSummary(value){
  if(Array.isArray(value)) return value.length ? value.slice(0, 4).map(item => settingsValueShort(item, 28)).join(' / ') : '没有配置项';
  if(value && typeof value === 'object'){
    const keys = Object.keys(value);
    return keys.length ? keys.slice(0, 5).join(' / ') : '空配置';
  }
  if(typeof value === 'boolean') return formatBool(value);
  return settingsValueShort(value || '-', 80);
}
function settingsValueShort(value, limit=80){
  let text;
  if(Array.isArray(value)) text = value.length ? value.slice(0, 4).map(item => settingsValueShort(item, 24)).join(', ') : '-';
  else if(value && typeof value === 'object') text = `${Object.keys(value).length} fields`;
  else if(typeof value === 'boolean') text = formatBool(value);
  else text = String(value ?? '-');
  return text.length > limit ? `${text.slice(0, Math.max(0, limit - 3))}...` : text;
}
function settingsGroupLabel(key){
  return ({
    collectors:'采集器',
    agent:'后台 Agent',
    retention:'长期保留',
    personal_memory:'个人记忆',
    email_reports:'邮件报告',
    file_analysis:'文件分析',
    recycle_bin:'回收箱',
    audio_analysis:'音频分析',
    speaker_recognition:'说话人',
    ai_backend:'AI 路由',
    local_ai:'本地 AI',
    openai_analysis:'OpenAI 备用',
    mobile_sync:'手机同步',
    watch_paths:'监控路径',
    browser_profiles:'浏览器资料',
    limits:'限制',
    data_dir:'数据目录',
    timezone:'时区',
  })[key] || key;
}
function settingsSearchKey(group){
  return [group.key, group.label, group.status, group.summary, JSON.stringify(group.value || '')].join(' ').toLowerCase();
}
function settingsGroupMatches(group, q){
  return settingsSearchKey(group).includes(String(q || '').toLowerCase());
}
function filterSettingsGroups(groups){
  const q = String(state.settingsQ || '').trim().toLowerCase();
  return q ? (groups || []).filter(group => settingsGroupMatches(group, q)) : (groups || []);
}
function applySettingsSearch(value){
  state.settingsQ = value || '';
  const q = String(state.settingsQ || '').trim().toLowerCase();
  const cards = Array.from(document.querySelectorAll('.settings-group-card'));
  let shown = 0;
  cards.forEach(card => {
    const hit = !q || String(card.dataset.search || '').includes(q);
    card.hidden = !hit;
    if(hit) shown += 1;
  });
  const count = $('settingsShownCount');
  if(count) count.textContent = `${shown} / ${cards.length} 组`;
  const empty = $('settingsEmpty');
  if(empty) empty.style.display = shown ? 'none' : '';
}
function setSettingsGroup(key){
  state.settingsGroup = key;
  settings().catch(e => toast(String(e)));
}
function runsTable(rows){ return `<div class="table-wrap"><table><thead><tr><th>Started</th><th>Collector</th><th>Status</th><th>Message</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.started_at)}</td><td>${esc(r.collector)}</td><td>${status(r.status)}</td><td>${esc(r.message||'')}</td></tr>`).join('')}</tbody></table></div>`; }
function sourceCountTable(rows){ return `<div class="table-wrap"><table><thead><tr><th>Source</th><th>Kind</th><th>Count</th><th>Latest</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${esc(r.source||'')}</td><td>${esc(r.kind)}</td><td>${esc(r.count)}</td><td>${esc(r.last||'')}</td></tr>`).join('')}</tbody></table></div>`; }
function obsList(rows){ return `<div class="list">${(rows||[]).map(o=>`<div class="item"><div class="item-title">${esc(o.title||o.subtitle||o.kind||o.name)}</div><div class="item-meta">${esc(o.observed_at||o.modified_at||'')} · ${esc(o.source||o.category||'')}/${esc(o.kind||'')}</div><div>${esc(o.body||o.summary||o.snippet||'')}</div></div>`).join('') || '<div class="muted">No records</div>'}</div>`; }
function eventList(rows){
  return `<div class="day-list">${(rows||[]).map(eventCard).join('') || '<div class="empty-state">No records</div>'}</div>`;
}
function eventSections(rows){
  if(!(rows||[]).length) return '<div class="empty-state">No records</div>';
  const groups = {late: [], morning: [], afternoon: [], evening: [], night: []};
  (rows || []).forEach(event => groups[dayPartKey(event.time)].push(event));
  return ['late','morning','afternoon','evening','night']
    .filter(key => groups[key].length)
    .map(key => `<section class="day-section"><div class="day-section-header"><h3>${esc(dayPartLabel(key))}</h3><span class="muted">${groups[key].length} 条</span></div><div class="day-list">${groups[key].map(eventCard).join('')}</div></section>`)
    .join('');
}
function eventCard(e){
  return `<div class="day-event">
    <div class="event-time">${esc(shortTime(e.time))}${e.end?`<br><span class="muted">${esc(shortTime(e.end))}</span>`:''}</div>
    <div>${categoryBadge(e.category)}${e.status?`<div style="margin-top:6px">${status(e.status)}</div>`:''}</div>
    <div><div class="event-title">${esc(e.title||e.kind)}</div><div class="event-meta">${eventMeta(e).map(part=>`<span>${esc(part)}</span>`).join('')}</div>${e.body?`<div class="event-body">${esc(e.body)}</div>`:''}</div>
  </div>`;
}
function eventMeta(e){
  const parts = [];
  if(e.source || e.kind) parts.push(`${e.source || ''}/${e.kind || ''}`);
  if((e.speakers || []).length) parts.push((e.speakers || []).join(' · '));
  if(e.actor) parts.push(e.actor);
  if(e.location) parts.push(e.location);
  if(e.app && e.app !== e.title) parts.push(e.app);
  return parts;
}
function categoryBadge(value){ const key=String(value||'other'); return `<span class="category ${esc(key)}">${esc(categoryLabel(key))}</span>`; }
function categoryLabel(value){
  return ({all:'全部',app:'App',audio:'录音',file:'文件',files:'文件',chat:'聊天',location:'位置',reminder:'提醒',calendar:'日程',bookmark:'标记',mail:'邮件',web:'网页',feedback:'反馈',system:'系统',other:'其他'})[value] || value;
}
function feedbackLabel(value){ return ({important:'重要',unimportant:'不重要',wrong:'错了',correction:'纠正'})[value] || value; }
function shortTime(value){ const text=String(value||''); const idx=text.indexOf('T'); return idx>=0 ? text.slice(idx+1, idx+6) : text; }
function shortDateTime(value){
  const text = String(value || '');
  const idx = text.indexOf('T');
  if(idx < 0) return text;
  return `${text.slice(0, idx)} ${text.slice(idx + 1, idx + 6)}`;
}
function shortRange(first, last){
  if(!first) return '无事件';
  const start = shortTime(first);
  const end = shortTime(last || first);
  return start === end ? start : `${start} → ${end}`;
}
function minutesOfDay(value){
  const time = shortTime(value).slice(0, 5);
  const parts = time.split(':');
  if(parts.length < 2) return -1;
  const hour = Number(parts[0]);
  const minute = Number(parts[1]);
  if(!Number.isFinite(hour) || !Number.isFinite(minute)) return -1;
  return hour * 60 + minute;
}
function dayPartKey(value){
  const minutes = minutesOfDay(value);
  if(minutes < 0 || minutes < 6 * 60) return 'late';
  if(minutes < 12 * 60) return 'morning';
  if(minutes < 18 * 60) return 'afternoon';
  if(minutes < 22 * 60) return 'evening';
  return 'night';
}
function dayPartLabel(value){
  return ({late:'凌晨',morning:'上午',afternoon:'下午',evening:'晚上',night:'深夜'})[value] || value;
}
function failureList(rows){
  return `<div class="list">${(rows||[]).map(f=>`<div class="item"><div class="item-title">${esc(f.title||'Audio failure')}</div><div class="item-meta">${esc(f.observed_at||'')}</div><div>${esc(f.error||'')}</div></div>`).join('') || '<div class="muted">No failures</div>'}</div>`;
}
function simpleMobileList(rows){
  return `<div class="list">${(rows||[]).map(r=>`<div class="item"><div class="item-title">${esc(r.title||r.kind)}</div><div class="item-meta">${esc(r.observed_at||'')} · ${esc(r.kind||'')} · captured ${esc(r.captured_at||'')}</div></div>`).join('') || '<div class="muted">No mobile records</div>'}</div>`;
}
function reportList(rows){ return `<div class="list">${(rows||[]).map(r=>`<div class="item"><div class="item-title">${esc(r.name)}</div><div class="item-meta">${esc(r.category)} · ${esc(r.modified_at)}</div><div>${esc(r.snippet||'')}</div></div>`).join('') || '<div class="muted">No reports</div>'}</div>`; }
function semanticList(rows){ return `<div class="list">${(rows||[]).map(r=>`<div class="item"><div class="item-title">${esc(r.title||r.key)}</div><div class="item-meta">score ${esc(r.score)} · ${esc(r.observed_at||'')} · ${esc(r.source||'')}/${esc(r.kind||'')}</div><div>${esc(r.text||'')}</div></div>`).join('') || '<div class="muted">No semantic matches yet. Build the index or check Ollama.</div>'}</div>`; }
function shortPath(value){ const text=String(value||''); if(!text || text === '-') return '-'; const parts=text.split('/').filter(Boolean); return parts.slice(-2).join('/') || text; }
function bytes(n){ n=Number(n||0); const units=['B','KB','MB','GB']; let i=0; while(n>=1024&&i<units.length-1){n/=1024;i++;} return `${n.toFixed(i?1:0)} ${units[i]}`; }
function routeHash(){
  const raw = location.hash.slice(1);
  const hash = canonicalSection(raw);
  if(isKnownSection(hash)){
    if(raw !== hash) history.replaceState(null,'','#'+hash);
    if(state.section !== hash){
      state.section = hash;
      render().catch(e=>toast(String(e)));
    }
  }
}
window.addEventListener('hashchange', routeHash);
window.addEventListener('load',()=>{ const raw=location.hash.slice(1); const hash=canonicalSection(raw); if(isKnownSection(hash)){ state.section=hash; if(raw && raw !== hash) history.replaceState(null,'','#'+hash); } nav(); startButtonTips(); startLocalization(); syncDashboardLanguageOnLoad().catch(()=>{}); render().catch(e=>toast(String(e))); });
</script>
</body>
</html>"""
