// Admin MVP 단일 페이지 — F6 입력 → POST /api/predict → 결과 + 근거 렌더링.

const fmt = new Intl.NumberFormat("ko-KR");
const won = (n) => n == null ? "-" : `${fmt.format(Math.round(n))} 원`;
const pct = (r) => r == null ? "-" : `${(r * 100).toFixed(1)}%`;

async function init() {
  await Promise.all([loadHealth(), loadModules(), loadProfile(), loadCoverage()]);
  document.getElementById("predict-form").addEventListener("submit", onSubmit);
  document.getElementById("upload-form").addEventListener("submit", onUpload);
}

async function onUpload(ev) {
  ev.preventDefault();
  const fileEl = document.getElementById("upload-file");
  const sheetEl = document.getElementById("upload-sheet");
  const resultEl = document.getElementById("upload-result");
  const btn = ev.target.querySelector("button");
  if (!fileEl.files.length) return;
  btn.disabled = true; btn.textContent = "분석 중...";
  resultEl.classList.remove("placeholder");
  resultEl.innerHTML = `<small>업로드 중... (${fileEl.files[0].name})</small>`;
  try {
    const fd = new FormData();
    fd.append("file", fileEl.files[0]);
    if (sheetEl.value) fd.append("sheet", sheetEl.value);
    fd.append("preview_rows", "10");
    if (document.getElementById("upload-save").checked) fd.append("save", "true");
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    if (!r.ok) {
      const txt = await r.text();
      throw new Error(`HTTP ${r.status}: ${txt}`);
    }
    renderUploadReport(await r.json());
  } catch (e) {
    resultEl.innerHTML = `<div class="warn">업로드 실패: ${e.message}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "분석";
  }
}

function renderUploadReport(rep) {
  const sheetInfo = rep.sheet_choices
    ? `시트: <b>${rep.sheet_name}</b> · 다른 시트로 재시도: ${rep.sheet_choices.map(s =>
        `<a href="#" data-sheet="${s.replace(/"/g, "&quot;")}" class="sheet-link">${s}</a>`
      ).join(" / ")}<br>`
    : "";
  const blockN = rep.issues.filter(i => i.severity === "block").length;
  const warnN  = rep.issues.filter(i => i.severity === "warn").length;
  const mappedRows = Object.entries(rep.column_mapping)
    .map(([std, src]) => `<tr><td>${std}</td><td>${src ?? "<span class=\"tag red\">미매핑</span>"}</td></tr>`)
    .join("");
  const previewKeys = ["raw_description", "actual_quantity", "unit", "unit_price", "total_amount", "vendor_name", "settlement_date", "project_name"];
  const previewHead = previewKeys.map(k => `<th>${k}</th>`).join("");
  const previewBody = rep.preview.map(p => {
    const matchTag = p.match_method === "exact"  ? `<span class="tag">exact</span>` :
                     p.match_method === "token"  ? `<span class="tag">token ${(p.match_score*100).toFixed(0)}%</span>` :
                                                   `<span class="tag red">미매핑</span>`;
    const matchInfo = p.matched_alias
      ? `<small>→ ${p.matched_alias} (mid=${p.matched_material_id ?? "-"})</small>` : "";
    return `<tr><td>${p.row}</td>${previewKeys.map(k => `<td class="num">${p[k] ?? ""}</td>`).join("")}<td>${matchTag}${matchInfo}</td></tr>`;
  }).join("");
  const previewHeadFull = `<th>row</th>${previewHead}<th>매핑</th>`;
  const issuesTop = rep.issues.slice(0, 8).map(i =>
    `<div class="warn" style="background:${i.severity === "block" ? "#fee2e2" : "#fef3c7"};color:${i.severity === "block" ? "#991b1b" : "#92400e"}">
      [${i.severity}] ${i.code}${i.row ? ` (행 ${i.row})` : ""}: ${i.message}
    </div>`
  ).join("");

  document.getElementById("upload-result").innerHTML = `
    <div style="font-size:13px;margin-bottom:8px">
      <b>${rep.source_filename}</b> · ${rep.source_type}<br>
      ${sheetInfo}
      총 <b>${fmt.format(rep.total_rows)}</b>행 · 정상 <b style="color:#065f46">${fmt.format(rep.accepted_rows)}</b> · 거부 <b style="color:#991b1b">${fmt.format(rep.rejected_rows)}</b>
      <span class="tag ${blockN ? "red" : "gray"}">block ${blockN}</span>
      <span class="tag gray">warn ${warnN}</span>
    </div>
    <details open>
      <summary>컬럼 매핑 (${rep.unmapped_columns.length}개 미매핑)</summary>
      <table><thead><tr><th>표준 필드</th><th>원본 헤더</th></tr></thead><tbody>${mappedRows}</tbody></table>
      ${rep.unmapped_columns.length ? `<small>미매핑 원본: ${rep.unmapped_columns.join(", ")}</small>` : ""}
    </details>
    <details open>
      <summary>미리보기 + alias 매칭 (${rep.preview.length}행) ${rep.alias_stats
        ? `· exact ${rep.alias_stats.matched_exact} / token ${rep.alias_stats.matched_token} / 매칭률 ${(rep.alias_stats.match_rate*100).toFixed(0)}%`
        : ""}</summary>
      <table style="font-size:11px"><thead><tr>${previewHeadFull}</tr></thead><tbody>${previewBody}</tbody></table>
    </details>
    ${rep.saved_to ? `<div class="warn" style="background:#dcfce7;color:#065f46">💾 저장됨: <code>${rep.saved_to}</code></div>` : ""}
    ${issuesTop ? `<details><summary>이슈 (상위 8개)</summary>${issuesTop}</details>` : ""}
  `;

  // sheet 링크 클릭 → 같은 파일을 해당 시트로 재업로드
  document.querySelectorAll(".sheet-link").forEach(a => {
    a.addEventListener("click", async (ev) => {
      ev.preventDefault();
      document.getElementById("upload-sheet").value = ev.target.dataset.sheet;
      document.getElementById("upload-form").requestSubmit();
    });
  });
}

async function loadHealth() {
  try {
    const r = await fetch("/api/health");
    const j = await r.json();
    document.getElementById("health").textContent =
      `actual_costs ${fmt.format(j.actual_costs)}행 · ${j.model_version}`;
  } catch (e) {
    document.getElementById("health").textContent = "DB 연결 실패";
  }
}

async function loadModules() {
  const r = await fetch("/api/modules");
  const { modules } = await r.json();
  const sel = document.getElementById("module");
  for (const m of modules) {
    const opt = document.createElement("option");
    opt.value = m.module_code;
    opt.textContent = `${m.module_code} · ${m.module_name} · ${m.floor_area_m2}㎡ · ${m.grade}`;
    sel.appendChild(opt);
  }
}

async function loadProfile() {
  const r = await fetch("/api/profile");
  const j = await r.json();
  const m = j.missing_rate;
  const lines = [
    `총 ${fmt.format(j.total_rows)}행`,
    `결측: 수량 ${pct(m.actual_quantity)} · 단위 ${pct(m.unit)} · 단가 ${pct(m.unit_price)} · material_id ${pct(m.material_id)}`,
    `vendor 오염(URL 혼입): ${fmt.format(j.vendor_polluted_rows)}행 (${pct(j.vendor_polluted_rate)})`,
    `promotion_status: ${j.by_promotion_status.map(x => `${x.promotion_status}=${x.n}`).join(", ")}`,
    `source_system: ${j.by_source_system.map(x => `${x.source_system}=${x.n}`).join(", ")}`,
  ];
  document.getElementById("profile-summary").textContent = lines.join("\n");
}

async function loadCoverage() {
  const r = await fetch("/api/coverage");
  const j = await r.json();
  const lines = [
    `description 보유 ${fmt.format(j.actual_costs_with_description)}행`,
    `material_id 매칭 ${fmt.format(j.matched_by_material_id)} (${pct(j.material_id_coverage_rate)})`,
    `alias 직매칭 ${fmt.format(j.matched_by_alias)} (${pct(j.alias_coverage_rate)})`,
    `material_aliases 마스터 ${fmt.format(j.material_aliases_total)}개`,
    "",
    "미매핑 raw_description 상위:",
    ...j.top_unmapped_descriptions.slice(0, 10).map(x => `  ${x.raw_description} (${x.n})`),
  ];
  document.getElementById("coverage-summary").textContent = lines.join("\n");
}

async function onSubmit(ev) {
  ev.preventDefault();
  const btn = ev.target.querySelector("button");
  btn.disabled = true; btn.textContent = "예측 중...";
  try {
    const body = {
      modules: [{
        module_code: document.getElementById("module").value,
        quantity: parseInt(document.getElementById("quantity").value, 10),
      }],
      loss_rate_default: numOrNull("loss_default"),
      loss_rate_lower:   numOrNull("loss_lower"),
      loss_rate_upper:   numOrNull("loss_upper"),
    };
    const r = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    renderResult(j);
    renderEvidence(j.evidence);
  } catch (e) {
    document.getElementById("result").innerHTML =
      `<div class="warn">예측 실패: ${e.message}</div>`;
  } finally {
    btn.disabled = false; btn.textContent = "예측 실행";
  }
}

function numOrNull(id) {
  const v = document.getElementById(id).value;
  return v === "" ? null : parseFloat(v);
}

function renderResult(r) {
  const warns = (r.modules?.[0]?.predicted?.warnings || [])
    .map(w => `<div class="warn">⚠ ${w}</div>`).join("");

  const kpis = [
    ["예측 총액 (P50)",     won(r.total),                  `±${won(r.confidence_upper - r.confidence_lower)}`],
    ["하한 (P25)",          won(r.confidence_lower),       null],
    ["상한 (P75)",          won(r.confidence_upper),       null],
    ["m²당 단가",           won(r.total_area_m2 ? r.total / r.total_area_m2 : 0), `${r.total_area_m2}㎡`],
  ];
  if (r.total_with_loss != null) {
    kpis.push(["로스 반영 총액", won(r.total_with_loss), `loss=${(r.loss_rate_applied*100).toFixed(1)}%`]);
  }

  const breakdown = (r.breakdown || []).map(b => `
    <tr>
      <td>${b.work_code}</td>
      <td>${b.work_name || ""}</td>
      <td>${b.cost_type}</td>
      <td class="num">${won(b.amount)}</td>
      <td class="num">${won(b.rate_per_m2)}/㎡</td>
      <td><span class="tag ${b.tier_used === "all" ? "gray" : ""}">${b.tier_used}</span></td>
      <td class="num">${b.sample_count}</td>
      <td class="num">${b.confidence}</td>
    </tr>
  `).join("");

  document.getElementById("result").innerHTML = `
    ${warns}
    <div class="kpi-row">
      ${kpis.map(([l, v, s]) => `
        <div class="kpi">
          <div class="label">${l}</div>
          <div class="value">${v}</div>
          ${s ? `<div class="sub">${s}</div>` : ""}
        </div>
      `).join("")}
    </div>
    <table>
      <thead><tr><th>공종</th><th>공종명</th><th>유형</th><th>금액</th><th>단가</th><th>tier</th><th>샘플</th><th>신뢰</th></tr></thead>
      <tbody>${breakdown}</tbody>
    </table>
  `;
}

function renderEvidence(ev) {
  if (!ev) {
    document.getElementById("evidence").innerHTML = "";
    return;
  }
  const features = ev.top_features.map(f => `
    <tr>
      <td>${f.work_code}</td>
      <td>${f.work_name}</td>
      <td>${f.cost_type}</td>
      <td class="num">${pct(f.contribution)}</td>
      <td class="num">${won(f.amount)}</td>
      <td><span class="tag ${f.tier_used === "all" ? "gray" : ""}">${f.tier_used}</span></td>
    </tr>
  `).join("");

  const similar = ev.similar_projects.map(p => `
    <tr>
      <td>${p.project_code}</td>
      <td>${p.module_code || "-"}</td>
      <td>${p.floor_area_m2}㎡</td>
      <td><span class="tag">${p.grade}</span></td>
      <td class="num">${won(p.actual_total)}</td>
      <td class="num">${(p.match_score * 100).toFixed(0)}%</td>
    </tr>
  `).join("");

  const q = ev.data_quality;
  const qLines = [
    ["학습 풀 샘플",      `${fmt.format(q.samples_in_pool)}개`],
    ["프로젝트 수",       `${q.projects_in_pool}개`],
    ["공종 커버",         `${q.work_codes_in_pool}개`],
    ["최신 결제일",       q.last_settlement || "-"],
    ["경과 개월",         q.months_since_last == null ? "-" : `${q.months_since_last}개월`],
    ["수량 결측률",       pct(q.actual_quantity_null_rate)],
  ];

  document.getElementById("evidence").innerHTML = `
    <div class="evidence-block">
      <h3>상위 영향 변수 (F7.1.1)</h3>
      <table>
        <thead><tr><th>공종</th><th>공종명</th><th>유형</th><th>기여도</th><th>금액</th><th>tier</th></tr></thead>
        <tbody>${features}</tbody>
      </table>
    </div>
    <div class="evidence-block">
      <h3>유사 프로젝트 (F7.1.2)</h3>
      <table>
        <thead><tr><th>프로젝트</th><th>모듈</th><th>면적</th><th>등급</th><th>실제 총액</th><th>유사도</th></tr></thead>
        <tbody>${similar}</tbody>
      </table>
    </div>
    <div class="evidence-block">
      <h3>데이터 품질 (F7 수용기준 #3)</h3>
      <div class="kpi-row">
        ${qLines.map(([l, v]) => `<div class="kpi"><div class="label">${l}</div><div class="value" style="font-size:14px">${v}</div></div>`).join("")}
      </div>
    </div>
  `;
}

init();
