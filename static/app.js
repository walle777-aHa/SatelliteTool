(() => {
  "use strict";

  const state = {
    info: null,
    currentJob: null,
    pollTimer: null,
    chartRows: [],
    chartColumns: [],
    tleResults: [],
    pollFailures: 0,
  };

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  async function api(path, options = {}) {
    const { timeoutMs = 30000, ...rest } = options;
    const init = { ...rest };
    if (init.body && typeof init.body !== "string") {
      init.body = JSON.stringify(init.body);
      init.headers = { "Content-Type": "application/json", ...(init.headers || {}) };
    }
    const controller = new AbortController();
    init.signal = controller.signal;
    const timer = window.setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetch(path, init);
      const text = await response.text();
      let data = null;
      try {
        data = text ? JSON.parse(text) : {};
      } catch (error) {
        throw new Error("服务器返回了非 JSON 内容");
      }
      if (!response.ok || data.ok === false) {
        throw new Error((data && data.error) || ("HTTP " + response.status));
      }
      return data;
    } catch (error) {
      if (error.name === "AbortError") throw new Error("请求超时");
      throw error;
    } finally {
      window.clearTimeout(timer);
    }
  }

  function fmtTime(value) {
    if (!value) return "-";
    if (typeof value === "number") {
      return new Date(value * 1000).toLocaleString();
    }
    return String(value);
  }

  function fmtBytes(value) {
    const number = Number(value || 0);
    if (number < 1024) return number + " B";
    if (number < 1024 * 1024) return (number / 1024).toFixed(1) + " KB";
    return (number / 1024 / 1024).toFixed(2) + " MB";
  }

  function badge(status) {
    const value = String(status || "unknown");
    return '<span class="badge ' + value + '">' + value + "</span>";
  }

  function toast(message, isError = false) {
    const element = $("#toast");
    element.textContent = message;
    element.classList.toggle("error", Boolean(isError));
    element.classList.add("show");
    window.clearTimeout(toast.timer);
    toast.timer = window.setTimeout(() => element.classList.remove("show"), 4200);
  }

  function switchPage(page, updateHash = true) {
    $$(".nav-btn").forEach((button) => {
      button.classList.toggle("active", button.dataset.page === page);
    });
    $$(".page").forEach((section) => {
      section.classList.toggle("active", section.id === "page-" + page);
    });
    if (page === "sim") loadJobs();
    if (updateHash && window.location.hash !== "#" + page) {
      window.location.hash = page;
    }
  }

  function pageFromHash() {
    const page = (window.location.hash || "#home").replace("#", "");
    return ["home", "sim", "aps", "tle", "query"].includes(page) ? page : "home";
  }

  async function loadInfo() {
    try {
      const data = await api("/api/info");
      state.info = data;
      const dot = $("#statusDot");
      const allExe = Object.values(data.executables || {}).every((item) => item.exists);
      dot.className = "dot " + (allExe ? "ok" : "bad");
      $("#statusText").textContent = allExe ? "就绪" : "缺少 exe";
      renderDataWarning(data);
      renderScenarios(data);
      renderProfiles(data);
      if (data.limits?.max_simulation_time_s) {
        $("#simulationTime").max = String(data.limits.max_simulation_time_s);
      }
    } catch (error) {
      $("#statusDot").className = "dot bad";
      $("#statusText").textContent = "连接失败";
      toast(error.message, true);
    }
  }

  function renderDataWarning(data) {
    const element = $("#dataWarning");
    if (!element) return;
    const eop = data.eop;
    if (eop?.available && Number(eop.stale_days) > 30) {
      element.textContent =
        "EOP 数据截止 " +
        (eop.last_date || "-") +
        "，已过期 " +
        eop.stale_days +
        " 天；涉及 UT1-UTC/极移的结果可能存在外推误差。";
      element.classList.remove("hidden");
    } else {
      element.textContent = "";
      element.classList.add("hidden");
    }
  }

  function renderScenarios(data) {
    const select = $("#scenarioSelect");
    const current = select.value;
    select.innerHTML = "";
    (data.scenarios || []).forEach((scenario) => {
      const option = document.createElement("option");
      option.value = scenario.name;
      option.textContent =
        scenario.name +
        (scenario.simulation_time != null ? " (" + scenario.simulation_time + " s)" : "");
      option.dataset.simulationTime =
        scenario.simulation_time == null ? "" : String(scenario.simulation_time);
      select.appendChild(option);
    });
    if (current) select.value = current;
    else if (data.default_scenario) select.value = data.default_scenario;
    updateScenarioHint();
  }

  function updateScenarioHint() {
    const select = $("#scenarioSelect");
    const option = select.selectedOptions[0];
    const defaultTime = option?.dataset.simulationTime || "";
    $("#simulationTime").placeholder = defaultTime
      ? "场景默认 " + defaultTime + " 秒"
      : "例如 100";
  }

  function renderProfiles(data) {
    const select = $("#profileSelect");
    const current = select.value;
    select.innerHTML = "";
    (data.profiles || []).forEach((profile) => {
      const option = document.createElement("option");
      option.value = profile.name;
      option.textContent = profile.name + (profile.columns ? " (" + profile.columns + " 列)" : "");
      select.appendChild(option);
    });
    if (current) select.value = current;
    else if (data.default_csv_profile) select.value = data.default_csv_profile;
    updateProfileNote();
  }

  function updateProfileNote() {
    const name = $("#profileSelect").value;
    const profile = (state.info?.profiles || []).find((item) => item.name === name);
    $("#profileNote").textContent = profile?.description || "";
  }

  async function loadJobs() {
    try {
      const data = await api("/api/jobs");
      const jobs = data.jobs || [];
      renderHistory(jobs);
      return jobs;
    } catch (error) {
      toast(error.message, true);
      return [];
    }
  }

  async function clearJobs() {
    if (!window.confirm("确定清理所有已完成的历史任务？正在运行的任务不会删除。")) {
      return;
    }
    try {
      const data = await api("/api/jobs", { method: "DELETE" });
      toast("已清理 " + (data.removed || 0) + " 个历史任务");
      await loadJobs();
    } catch (error) {
      toast(error.message, true);
    }
  }

  function renderHistory(jobs) {
    const container = $("#jobHistory");
    if (!jobs.length) {
      container.innerHTML = '<p class="hint">暂无历史任务。</p>';
      return;
    }
    container.innerHTML = "";
    jobs.forEach((job) => {
      const item = document.createElement("button");
      item.className = "history-item";
      item.innerHTML =
        "<span><strong>" + escapeHtml(job.scenario || job.id) + "</strong>" +
        "<small>" + fmtTime(job.created_at) + " · " + escapeHtml(job.csv_profile || "") + "</small></span>" +
        badge(job.status);
      item.addEventListener("click", () => openJob(job.id));
      container.appendChild(item);
    });
  }

  async function openJob(jobId) {
    stopPolling();
    switchPage("sim");
    try {
      const data = await api("/api/jobs/" + encodeURIComponent(jobId) + "?limit=20");
      renderJob(data.job);
      if (data.job.status === "running") startPolling(jobId);
    } catch (error) {
      toast(error.message, true);
    }
  }

  function startPolling(jobId) {
    stopPolling();
    state.pollFailures = 0;
    const tick = async () => {
      try {
        const data = await api("/api/jobs/" + encodeURIComponent(jobId) + "?limit=20");
        state.pollFailures = 0;
        renderJob(data.job);
        if (data.job.status === "running") {
          state.pollTimer = window.setTimeout(tick, 1000);
        } else {
          state.pollTimer = null;
          loadJobs();
        }
      } catch (error) {
        toast(error.message, true);
        state.pollFailures += 1;
        if (state.pollFailures <= 5) {
          state.pollTimer = window.setTimeout(tick, 3000);
        } else {
          state.pollTimer = null;
        }
      }
    };
    state.pollTimer = window.setTimeout(tick, 500);
  }

  function stopPolling() {
    if (state.pollTimer) {
      window.clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function renderJob(job) {
    state.currentJob = job;
    const info = [
      ["状态", badge(job.status)],
      ["场景", escapeHtml(job.scenario || "-")],
      ["CSV 配置", escapeHtml(job.csv_profile || "-")],
      ["退出码", job.exit_code === null || job.exit_code === undefined ? "-" : String(job.exit_code)],
      ["开始", escapeHtml(job.started_at || "-")],
      ["完成", escapeHtml(job.completed_at || "-")],
    ];
    if (job.telemetry) {
      info.push(["导出", job.telemetry.row_count + " 行 · " + job.telemetry.columns.length + " 列"]);
    }
    if (job.preview && job.preview.chart_rows && job.preview.chart_rows.length) {
      const first = job.preview.chart_rows[0];
      const last = job.preview.chart_rows[job.preview.chart_rows.length - 1];
      info.push(["数据范围", escapeHtml(first[0]) + " – " + escapeHtml(last[0])]);
    }
    if (job.preview && job.preview.truncated) {
      info.push([
        "预览范围",
        "仅扫描前 " + Number(job.preview.row_count || 0).toLocaleString() + " 行",
      ]);
    }
    if (job.error) info.push(["错误", '<span class="error-text">' + escapeHtml(job.error) + "</span>"]);

    const infoGrid = $("#jobInfo");
    infoGrid.innerHTML = info
      .map(([key, value]) => "<div><dt>" + key + "</dt><dd>" + value + "</dd></div>")
      .join("");

    const oldFiles = infoGrid.parentElement.querySelector(".job-files");
    if (oldFiles) oldFiles.remove();
    if (job.files && job.files.length) {
      const files = document.createElement("div");
      files.className = "job-files";
      files.innerHTML =
        '<div class="panel-title">产物</div>' +
        job.files
          .map(
            (file) =>
              '<a class="file-link" href="/api/jobs/' +
              encodeURIComponent(job.id) +
              "/file?name=" +
              encodeURIComponent(file.name) +
              '">' +
              escapeHtml(file.name) +
              " <small>" +
              fmtBytes(file.size) +
              "</small></a>"
          )
          .join("");
      infoGrid.parentElement.appendChild(files);
    }

    const running = job.status === "running";
    $("#runSimulation").disabled = running;
    $("#stopSimulation").disabled = !running;
    $("#downloadCsv").classList.toggle("hidden", !job.files?.some((file) => file.name === "telemetry.csv"));
    $("#downloadRaw").classList.toggle("hidden", !job.files?.some((file) => file.name === "output/sim_data.csv"));
    if (job.files?.some((file) => file.name === "telemetry.csv")) {
      $("#downloadCsv").href = "/api/jobs/" + encodeURIComponent(job.id) + "/file?name=telemetry.csv";
    }
    if (job.files?.some((file) => file.name === "output/sim_data.csv")) {
      $("#downloadRaw").href =
        "/api/jobs/" + encodeURIComponent(job.id) + "/file?name=" + encodeURIComponent("output/sim_data.csv");
    }

    if (job.preview) {
      renderPreview(job.preview);
    } else {
      state.chartRows = [];
      state.chartColumns = [];
      $("#chartColumn").innerHTML = "";
      $("#telemetryTable thead").innerHTML = "";
      $("#telemetryTable tbody").innerHTML = "";
      drawChart();
    }
    loadJobLog(job.id, running);
  }

  async function loadJobLog(jobId, running) {
    try {
      const data = await api(
        "/api/jobs/" + encodeURIComponent(jobId) + "/log?tail=65536",
        { timeoutMs: 15000 }
      );
      if (state.currentJob?.id !== jobId) return;
      const consoleElement = $("#jobLog");
      consoleElement.textContent = data.text || "等待日志...";
      consoleElement.scrollTop = consoleElement.scrollHeight;
      if (running) {
        window.setTimeout(() => {
          if (state.currentJob?.id === jobId && state.currentJob.status === "running") {
            loadJobLog(jobId, true);
          }
        }, 1000);
      }
    } catch (error) {
      if (state.currentJob?.id === jobId) {
        $("#jobLog").textContent = error.message;
      }
    }
  }

  function renderPreview(preview) {
    const columns = preview.columns || [];
    const rows = preview.rows || [];
    state.chartColumns = columns;
    state.chartRows = preview.chart_rows || rows;

    const thead = $("#telemetryTable thead");
    const tbody = $("#telemetryTable tbody");
    thead.innerHTML =
      "<tr>" +
      columns.map((column) => '<th scope="col">' + escapeHtml(column) + "</th>").join("") +
      "</tr>";
    tbody.innerHTML = rows
      .map(
        (row) =>
          "<tr>" + row.map((cell) => "<td>" + escapeHtml(cell) + "</td>").join("") + "</tr>"
      )
      .join("");

    const select = $("#chartColumn");
    const current = select.value;
    select.innerHTML = columns
      .map((column, index) => '<option value="' + index + '">' + escapeHtml(column) + "</option>")
      .join("");
    if (current && Number(current) < columns.length) select.value = current;
    drawChart();
  }

  function drawChart() {
    const canvas = $("#telemetryChart");
    const context = canvas.getContext("2d");
    const ratio = window.devicePixelRatio || 1;
    const width = Math.max(320, canvas.clientWidth);
    const height = 280;
    canvas.width = Math.floor(width * ratio);
    canvas.height = Math.floor(height * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);
    context.clearRect(0, 0, width, height);

    const columns = state.chartColumns;
    const rows = state.chartRows;
    canvas.setAttribute("aria-label", "遥测曲线：暂无数据");
    if (!columns.length || !rows.length) return;
    const columnIndex = Number($("#chartColumn").value || 0);
    const xIndex = 0;
    const points = [];
    rows.forEach((row, index) => {
      const y = Number(row[columnIndex]);
      const x = Number(row[xIndex]);
      if (Number.isFinite(y) && Number.isFinite(x)) points.push({ x, y, index });
    });
    if (points.length < 2) {
      canvas.setAttribute("aria-label", "遥测曲线：数据不足");
      return;
    }

    const padding = { left: 52, right: 16, top: 18, bottom: 30 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const minX = points[0].x;
    const maxX = points[points.length - 1].x;
    const minY = Math.min(...points.map((point) => point.y));
    const maxY = Math.max(...points.map((point) => point.y));
    const spanX = maxX - minX || 1;
    const spanY = maxY - minY || 1;

    context.strokeStyle = "#2a313b";
    context.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + (plotHeight * i) / 4;
      context.beginPath();
      context.moveTo(padding.left, y);
      context.lineTo(width - padding.right, y);
      context.stroke();
    }

    context.strokeStyle = "#4dd4c6";
    context.lineWidth = 2;
    context.beginPath();
    points.forEach((point, index) => {
      const x = padding.left + ((point.x - minX) / spanX) * plotWidth;
      const y = padding.top + (1 - (point.y - minY) / spanY) * plotHeight;
      if (index === 0) context.moveTo(x, y);
      else context.lineTo(x, y);
    });
    context.stroke();

    context.fillStyle = "#8e9aa8";
    context.font = "11px Consolas, monospace";
    context.fillText(formatTick(maxY), 8, padding.top + 4);
    context.fillText(formatTick(minY), 8, padding.top + plotHeight);
    context.fillText(formatTick(minX), padding.left, height - 8);
    context.fillText(formatTick(maxX), width - padding.right - 48, height - 8);
    canvas.setAttribute(
      "aria-label",
      "遥测曲线：" +
        (columns[columnIndex] || "数值") +
        "，范围 " +
        formatTick(minX) +
        " 至 " +
        formatTick(maxX)
    );
  }

  function formatTick(value) {
    if (!Number.isFinite(value)) return "-";
    const absolute = Math.abs(value);
    if (absolute !== 0 && (absolute < 0.001 || absolute >= 100000)) return value.toExponential(2);
    return value.toFixed(3);
  }

  async function runSimulation() {
    stopPolling();
    const body = {
      scenario: $("#scenarioSelect").value,
      csv_profile: $("#profileSelect").value,
      simulation_time: $("#simulationTime").value.trim() || null,
    };
    try {
      $("#runSimulation").disabled = true;
      const data = await api("/api/run", { method: "POST", body, timeoutMs: 30000 });
      renderJob({ ...data.job, files: [], preview: null });
      $("#jobLog").textContent = "任务已启动...";
      startPolling(data.job.id);
      loadJobs();
    } catch (error) {
      $("#runSimulation").disabled = false;
      toast(error.message, true);
    }
  }

  async function stopSimulation() {
    if (!state.currentJob) return;
    try {
      await api("/api/jobs/" + encodeURIComponent(state.currentJob.id) + "/stop", {
        method: "POST",
        body: {},
      });
      toast("已请求停止");
    } catch (error) {
      toast(error.message, true);
    }
  }

  function formatElement(value) {
    if (value === undefined || value === null || value === "") return "";
    const number = Number(value);
    if (!Number.isFinite(number)) return String(value);
    return Number(number.toPrecision(12)).toString();
  }

  function formatApsMeanText(result) {
    if (!result || !result.mean) return "";
    const rows = [
      ["a (km)", "a_km"],
      ["e", "e"],
      ["i (deg)", "i_deg"],
      ["Ω (deg)", "raan_deg"],
      ["ω (deg)", "argp_deg"],
      ["M (deg)", "m_deg"],
    ];
    return rows
      .map(([label, key]) => label + "\t" + formatElement(result.mean[key]))
      .join("\n");
  }

  function clearApsResult() {
    ["A", "E", "I", "Raan", "Argp", "M"].forEach((suffix) => {
      ["In", "Osc", "Mean"].forEach((prefix) => {
        $("#aps" + prefix + suffix).value = "";
      });
    });
  }

  function fillApsGroup(prefix, group) {
    if (!group) return;
    const fields = {
      A: "a_km",
      E: "e",
      I: "i_deg",
      Raan: "raan_deg",
      Argp: "argp_deg",
      M: "m_deg",
    };
    Object.entries(fields).forEach(([suffix, key]) => {
      $("#aps" + prefix + suffix).value = formatElement(group[key]);
    });
  }

  async function copyText(content, message) {
    try {
      await navigator.clipboard.writeText(content);
      toast(message || "已复制");
    } catch (error) {
      const area = document.createElement("textarea");
      area.value = content;
      area.style.position = "fixed";
      area.style.opacity = "0";
      document.body.appendChild(area);
      area.select();
      try {
        if (!document.execCommand("copy")) throw new Error("copy failed");
        toast(message || "已复制");
      } catch (fallbackError) {
        toast("复制失败", true);
      } finally {
        area.remove();
      }
    }
  }

  async function submitAps(event) {
    event.preventDefault();
    const body = {
      mode: $("#apsMode").value,
      epoch: $("#apsEpoch").value.trim(),
      a_km: $("#apsA").value,
      e: $("#apsE").value,
      i_deg: $("#apsI").value,
      raan_deg: $("#apsRaan").value,
      argp_deg: $("#apsArgp").value,
      m_deg: $("#apsM").value,
    };
    clearApsResult();
    const submit = $("#apsForm").querySelector('button[type="submit"]');
    submit.disabled = true;
    $("#apsMeta").textContent = "计算中...";
    $("#copyAps").disabled = true;
    delete $("#copyAps").dataset.text;
    try {
      const data = await api("/api/aps", {
        method: "POST",
        body,
        timeoutMs: 60000,
      });
      const result = data.result;
      fillApsGroup("In", result.input);
      fillApsGroup("Osc", result.osculating);
      fillApsGroup("Mean", result.mean);
      const direction = result.mode === "o2m" ? "瞬根 → 平根" : "平根 → 瞬根";
      $("#apsMeta").textContent =
        "模式 " + direction + " · 历元 " + (result.epoch || "-") +
        (result.end_of_life ? " · 近地点过低" : "");
      $("#copyAps").dataset.text = formatApsMeanText(result);
      $("#copyAps").disabled = false;
    } catch (error) {
      $("#apsMeta").textContent = error.message;
      toast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  }

  async function submitTle(event) {
    event.preventDefault();
    const body = {
      line1: $("#tleLine1").value.trim(),
      line2: $("#tleLine2").value.trim(),
      duration_days: $("#tleDuration").value,
      step_minutes: $("#tleStep").value,
      sample_minutes: $("#tleSample").value,
    };
    const submit = $("#tleForm").querySelector('button[type="submit"]');
    submit.disabled = true;
    $("#tleMeta").textContent = "递推中...";
    try {
      const data = await api("/api/sgp4", {
        method: "POST",
        body,
        timeoutMs: 60000,
      });
      const result = data.result;
      $("#tleMeta").textContent =
        "TLE 历元: " + (result.tle_epoch || "-") + "\n采样点数: " + (result.sample_count || 0);
      const samples = result.samples || [];
      $("#tleTable thead").innerHTML =
        "<tr><th scope=\"col\">t_min</th><th scope=\"col\">UTC</th><th scope=\"col\">X (km)</th><th scope=\"col\">Y (km)</th><th scope=\"col\">Z (km)</th><th scope=\"col\">VX (km/s)</th><th scope=\"col\">VY (km/s)</th><th scope=\"col\">VZ (km/s)</th></tr>";
      $("#tleTable tbody").innerHTML = samples
        .map(
          (sample) =>
            "<tr><td>" + Number(sample.t_min).toFixed(2) + "</td><td>" + escapeHtml(sample.utc || "") +
            "</td>" + (sample.r_km || []).map((value) => "<td>" + Number(value).toFixed(3) + "</td>").join("") +
            (sample.v_km_s || []).map((value) => "<td>" + Number(value).toFixed(6) + "</td>").join("") +
            "</tr>"
        )
        .join("");
    } catch (error) {
      $("#tleMeta").textContent = error.message;
      toast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  }

  async function queryTle() {
    const container = $("#queryResults");
    state.tleResults = [];
    const queryButton = $("#queryTle");
    queryButton.disabled = true;
    $("#copyAllTle").disabled = true;
    container.innerHTML = '<p class="hint">查询中...</p>';
    try {
      const data = await api("/api/celestrak", {
        method: "POST",
        body: { norad_ids: $("#noradIds").value },
        timeoutMs: 90000,
      });
      const results = data.results || [];
      state.tleResults = results;
      if (!results.length) {
        container.innerHTML = '<p class="hint">没有结果。</p>';
        return;
      }
      const rows = results
        .map((item, index) => {
          if (!item.ok) {
            return (
              "<tr><td>NORAD " + escapeHtml(item.norad_id) + "</td><td>" +
              escapeHtml(item.norad_id) + "</td><td>-</td><td>-</td>" +
              '<td class="error-text">' + escapeHtml(item.error || "查询失败") +
              "</td><td>-</td></tr>"
            );
          }
          const identity = item.object_id
            ? escapeHtml(item.name) + '<br><small>' + escapeHtml(item.object_id) + "</small>"
            : escapeHtml(item.name);
          return (
            "<tr><td>" + identity + "</td><td>" + escapeHtml(item.norad_id) +
            "</td><td>" + escapeHtml(item.launch_date || "-") +
            "</td><td>" + escapeHtml(item.tle_epoch || "-") +
            '</td><td class="tle-lines">' +
            escapeHtml(item.tle_line1) + "\n" + escapeHtml(item.tle_line2) +
            (item.warning ? '\n<span class="error-text">' + escapeHtml(item.warning) + "</span>" : "") +
            '</td><td><button class="btn ghost copy-tle" type="button" data-index="' +
            index + '">复制</button></td></tr>'
          );
        })
        .join("");
      container.innerHTML =
        '<table><thead><tr><th scope="col">名称</th><th scope="col">NORAD</th>' +
        '<th scope="col">入轨日期</th><th scope="col">TLE 历元</th>' +
        '<th scope="col">TLE</th><th scope="col">操作</th></tr></thead>' +
        "<tbody>" + rows + "</tbody></table>";
      $("#copyAllTle").disabled = !results.some((item) => item.ok);
      $$(".copy-tle", container).forEach((button) => {
        button.addEventListener("click", () => copyTle(Number(button.dataset.index)));
      });
    } catch (error) {
      container.innerHTML = '<p class="error-text">' + escapeHtml(error.message) + "</p>";
      toast(error.message, true);
    } finally {
      queryButton.disabled = false;
    }
  }

  function copyTle(index) {
    const item = state.tleResults[index];
    if (!item || !item.ok) return;
    copyText(
      item.tle_line1 + "\n" + item.tle_line2,
      "已复制 " + (item.name || ("NORAD " + item.norad_id)) + " TLE"
    );
  }

  function copyAllTle() {
    const items = state.tleResults.filter((item) => item.ok);
    if (!items.length) return;
    const content = items
      .map((item) => item.name + "\n" + item.tle_line1 + "\n" + item.tle_line2)
      .join("\n\n");
    copyText(content, "已复制 " + items.length + " 颗 TLE");
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#39;");
  }

  function labelApsResultInputs() {
    const table = $(".aps-result-table");
    if (!table) return;
    const headers = Array.from(table.querySelectorAll("thead th")).map((th) =>
      th.textContent.trim()
    );
    table.querySelectorAll("tbody tr").forEach((row) => {
      const rowHeader = row.querySelector("th");
      if (rowHeader) rowHeader.scope = "row";
      const label = rowHeader?.textContent.trim() || "";
      row.querySelectorAll("td input").forEach((input, index) => {
        input.setAttribute("aria-label", (headers[index + 1] || "值") + " " + label);
      });
    });
  }

  function initWalle() {
    const robot = $(".walle");
    const actor = $(".walle-actor");
    const home = $("#page-home");
    if (!robot || !actor || !home) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const keys = new Set();
    const autoSpeed = () => Math.max(48, home.clientWidth * 0.06);
    const manualSpeed = () => Math.max(240, home.clientWidth * 0.28);
    const verticalSpeed = () => Math.max(220, home.clientHeight * 0.32);
    const resumeDelay = 1800;
    let width = robot.offsetWidth || 132;
    let height = robot.offsetHeight || 130;
    let x = 0;
    let y = 0;
    let direction = 1;
    let manualUntil = 0;
    let positioned = false;
    let lastTime = 0;

    const isHome = () => home.classList.contains("active");
    const isFormTarget = (target) =>
      target?.isContentEditable ||
      ["INPUT", "TEXTAREA", "SELECT"].includes(target?.tagName);

    const measure = () => {
      width = robot.offsetWidth || width;
      height = robot.offsetHeight || height;
    };

    const setDirection = (value) => {
      direction = value < 0 ? -1 : 1;
      actor.style.transform = direction === 1 ? "scaleX(1)" : "scaleX(-1)";
    };

    const place = () => {
      robot.style.transform = "translate3d(" + x + "px, " + y + "px, 0)";
    };

    const clampY = () => {
      y = Math.max(0, Math.min(y, Math.max(0, home.clientHeight - height)));
    };

    const wrapY = () => {
      if (y > home.clientHeight) {
        y = -height;
      } else if (y < -height) {
        y = home.clientHeight;
      }
    };

    const wrapX = () => {
      if (x > home.clientWidth) {
        x = -width;
        setDirection(1);
      } else if (x < -width) {
        x = home.clientWidth;
        setDirection(-1);
      }
    };

    const position = () => {
      if (!isHome()) return;
      measure();
      if (!positioned) {
        x = Math.max(0, home.clientWidth * 0.04);
        y = Math.max(0, home.clientHeight * 0.9 - height);
        positioned = true;
        setDirection(1);
      } else {
        clampY();
        if (x > home.clientWidth + width) x = -width;
        if (x < -width * 2) x = home.clientWidth;
      }
      place();
      robot.classList.add("is-ready");
    };

    const onKeyDown = (event) => {
      if (!isHome() || isFormTarget(event.target)) return;
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
        return;
      }
      event.preventDefault();
      if (!positioned) position();
      keys.add(event.key);
      manualUntil = performance.now() + resumeDelay;
      robot.classList.add("is-manual");
      if (event.key === "ArrowLeft") setDirection(-1);
      if (event.key === "ArrowRight") setDirection(1);
      if (!event.repeat) {
        if (event.key === "ArrowLeft") x -= 10;
        if (event.key === "ArrowRight") x += 10;
        if (event.key === "ArrowUp") y -= 10;
        if (event.key === "ArrowDown") y += 10;
        wrapX();
        wrapY();
        place();
      }
    };

    const onKeyUp = (event) => {
      if (!["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)) {
        return;
      }
      keys.delete(event.key);
      if (!keys.size) robot.classList.remove("is-manual");
    };

    const clearKeys = () => {
      keys.clear();
      robot.classList.remove("is-manual");
    };

    const onResize = () => {
      if (!positioned || !isHome()) return;
      measure();
      clampY();
      if (x > home.clientWidth + width) x = -width;
      place();
    };

    const tick = (time) => {
      const dt = lastTime ? Math.min(0.05, (time - lastTime) / 1000) : 0;
      lastTime = time;
      if (!isHome()) {
        requestAnimationFrame(tick);
        return;
      }
      if (!positioned) position();
      const manual = keys.size > 0 || performance.now() < manualUntil;
      if (manual) {
        let dx = 0;
        let dy = 0;
        if (keys.has("ArrowLeft")) dx -= 1;
        if (keys.has("ArrowRight")) dx += 1;
        if (keys.has("ArrowUp")) dy -= 1;
        if (keys.has("ArrowDown")) dy += 1;
        if (dx !== 0) {
          x += dx * manualSpeed() * dt;
          setDirection(dx);
          wrapX();
        }
        if (dy !== 0) {
          y += dy * verticalSpeed() * dt;
          wrapY();
        }
        if (keys.size) manualUntil = performance.now() + 500;
        place();
      } else if (!reducedMotion) {
        x += direction * autoSpeed() * dt;
        wrapX();
        place();
      }
      requestAnimationFrame(tick);
    };

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", clearKeys);
    window.addEventListener("resize", onResize);
    document.addEventListener("visibilitychange", () => {
      lastTime = 0;
    });
    window.addEventListener("hashchange", () => {
      if (isHome()) position();
      else clearKeys();
    });
    position();
    requestAnimationFrame(tick);
  }

  function bind() {
    $$(".nav-btn").forEach((button) => {
      button.addEventListener("click", () => switchPage(button.dataset.page));
    });
    $$(".home-shortcut").forEach((button) => {
      button.addEventListener("click", () => switchPage(button.dataset.go));
    });
    $("#runSimulation").addEventListener("click", runSimulation);
    $("#stopSimulation").addEventListener("click", stopSimulation);
    $("#profileSelect").addEventListener("change", updateProfileNote);
    $("#chartColumn").addEventListener("change", drawChart);
    $("#refreshJobs").addEventListener("click", loadJobs);
    $("#clearJobs").addEventListener("click", clearJobs);
    $("#scenarioSelect").addEventListener("change", updateScenarioHint);
    $("#apsForm").addEventListener("submit", submitAps);
    $("#copyAps").addEventListener("click", () => {
      const content = $("#copyAps").dataset.text;
      if (content) copyText(content, "已复制平根参数");
    });
    $("#tleForm").addEventListener("submit", submitTle);
    $("#queryTle").addEventListener("click", queryTle);
    $("#copyAllTle").addEventListener("click", copyAllTle);
    labelApsResultInputs();
    window.addEventListener("hashchange", () => {
      const page = pageFromHash();
      const active = $(".page.active");
      if (active?.id !== "page-" + page) switchPage(page, false);
    });
    window.addEventListener("resize", drawChart);
  }

  async function boot() {
    bind();
    initWalle();
    const page = pageFromHash();
    switchPage(page, false);
    await loadInfo();
    const jobs = await loadJobs();
    if (page === "sim") {
      const running = jobs.find((job) => job.status === "running");
      if (running) await openJob(running.id);
    }
  }

  boot();
})();
