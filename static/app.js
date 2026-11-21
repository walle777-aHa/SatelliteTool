(() => {
  "use strict";

  const state = {
    info: null,
    currentJob: null,
    pollTimer: null,
    chartRows: [],
    chartColumns: [],
    tleResults: [],
    tleSamples: [],
    savedNoradIds: [],
    recentLaunches: null,
    recentLaunchesAt: 0,
    recentLaunchesLoading: false,
    drag: null,
    f107: null,
    f107Loading: false,
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
    if (page === "query") {
      loadSavedNoradIds();
      if (
        !state.recentLaunches ||
        Date.now() - state.recentLaunchesAt > 5 * 60 * 1000
      ) {
        loadRecentLaunches();
      }
    }
    if (page === "f107") {
      if (!state.f107 && !state.f107Loading) {
        loadF107();
      } else if (state.f107) {
        window.requestAnimationFrame(drawF107Chart);
      }
    }
    if (updateHash && window.location.hash !== "#" + page) {
      window.location.hash = page;
    }
  }

  function pageFromHash() {
    const page = (window.location.hash || "#home").replace("#", "");
    return ["home", "sim", "aps", "tle", "query", "f107"].includes(page)
      ? page
      : "home";
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
      $("#dataWarningText").textContent =
        "EOP 数据截止 " +
        (eop.last_date || "-") +
        "，已过期 " +
        eop.stale_days +
        " 天；涉及 UT1-UTC/极移的结果可能存在外推误差。";
      element.classList.remove("hidden");
    } else {
      $("#dataWarningText").textContent = "";
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

  function formatF107Value(value) {
    return typeof value === "number" && Number.isFinite(value)
      ? value.toFixed(1)
      : "-";
  }

  async function loadF107(force = false) {
    if (state.f107Loading) return;
    state.f107Loading = true;
    const button = $("#f107Refresh");
    const message = $("#f107Message");
    button.disabled = true;
    message.className = "hint";
    message.textContent = force ? "正在刷新 F10.7 数据..." : "正在加载 F10.7 数据...";
    try {
      const data = await api("/api/f107" + (force ? "?refresh=1" : ""), {
        timeoutMs: 30000,
      });
      state.f107 = data;
      renderF107(data);
      message.className = data.stale ? "hint f107-warning" : "hint";
      message.textContent = data.stale
        ? "数据源暂不可用，显示缓存结果"
        : "数据已更新";
    } catch (error) {
      message.className = "hint error-text";
      message.textContent = error.message;
    } finally {
      state.f107Loading = false;
      button.disabled = false;
    }
  }

  function renderF107(data) {
    const latest = data.latest || {};
    const range = data.range || {};
    $("#f107LatestFlux").textContent = formatF107Value(latest.flux);
    $("#f107LatestDate").textContent = latest.date
      ? "观测日期 " + latest.date + " · 1 AU"
      : "-";
    $("#f107Last81").textContent = formatF107Value(latest.last81);
    $("#f107SampleCount").textContent = (range.count || 0) + " 天";
    $("#f107SampleRange").textContent =
      (range.start || "-") + " → " + (range.end || "-");
    $("#f107ChartMeta").textContent =
      (range.start || "-") +
      " – " +
      (range.end || "-") +
      " · " +
      (range.count || 0) +
      " 个日观测";
    $("#f107Cards").hidden = false;
    $("#f107ChartBox").hidden = false;
    $("#f107Copy").disabled = !(data.series && data.series.length);
    const warning = $("#f107Warning");
    warning.textContent = data.warning || "";
    warning.hidden = !data.warning;
    window.requestAnimationFrame(drawF107Chart);
  }

  function drawF107Chart() {
    const canvas = $("#f107Chart");
    const data = state.f107;
    if (!canvas || !data) return;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    if (width < 2 || height < 2) return;
    const ratio = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.floor(width * ratio));
    canvas.height = Math.max(1, Math.floor(height * ratio));
    const ctx = canvas.getContext("2d");
    ctx.setTransform(ratio, 0, 0, ratio, 0, 0);
    ctx.clearRect(0, 0, width, height);

    const rows = (data.series || []).filter(
      (item) => typeof item.flux === "number" && Number.isFinite(item.flux)
    );
    if (rows.length < 2) {
      ctx.fillStyle = "#8e9aa8";
      ctx.font = "13px Consolas, monospace";
      ctx.fillText("F10.7 日观测数据不足", 20, 30);
      return;
    }

    const padding = { left: 56, right: 24, top: 38, bottom: 38 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    const values = [];
    rows.forEach((item) => {
      values.push(item.flux);
      if (typeof item.last81 === "number" && Number.isFinite(item.last81)) {
        values.push(item.last81);
      }
    });
    let minY = Math.min(...values);
    let maxY = Math.max(...values);
    if (minY === maxY) {
      minY -= 1;
      maxY += 1;
    }
    const yPadding = Math.max(5, (maxY - minY) * 0.12);
    minY -= yPadding;
    maxY += yPadding;
    const mapX = (index) =>
      padding.left + (index / (rows.length - 1)) * plotWidth;
    const mapY = (value) =>
      padding.top + (1 - (value - minY) / (maxY - minY)) * plotHeight;

    ctx.strokeStyle = "#2a313b";
    ctx.fillStyle = "#8e9aa8";
    ctx.font = "11px Consolas, monospace";
    ctx.lineWidth = 1;
    for (let i = 0; i <= 4; i += 1) {
      const y = padding.top + (plotHeight * i) / 4;
      ctx.beginPath();
      ctx.moveTo(padding.left, y);
      ctx.lineTo(width - padding.right, y);
      ctx.stroke();
      const value = maxY - ((maxY - minY) * i) / 4;
      ctx.fillText(value.toFixed(0), 8, y + 4);
    }
    for (let i = 0; i <= 4; i += 1) {
      const x = padding.left + (plotWidth * i) / 4;
      ctx.beginPath();
      ctx.moveTo(x, padding.top);
      ctx.lineTo(x, height - padding.bottom);
      ctx.stroke();
      const index = Math.round(((rows.length - 1) * i) / 4);
      ctx.fillText(rows[index].date.slice(5), x - 18, height - padding.bottom + 20);
    }

    ctx.save();
    ctx.beginPath();
    ctx.rect(padding.left, padding.top, plotWidth, plotHeight);
    ctx.clip();

    ctx.beginPath();
    ctx.moveTo(mapX(0), padding.top + plotHeight);
    rows.forEach((item, index) => {
      ctx.lineTo(mapX(index), mapY(item.flux));
    });
    ctx.lineTo(mapX(rows.length - 1), padding.top + plotHeight);
    ctx.closePath();
    ctx.fillStyle = "rgba(77, 212, 198, 0.08)";
    ctx.fill();

    ctx.strokeStyle = "#4dd4c6";
    ctx.lineWidth = 2;
    ctx.beginPath();
    rows.forEach((item, index) => {
      const x = mapX(index);
      const y = mapY(item.flux);
      if (index === 0) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    });
    ctx.stroke();

    const meanPoints = [];
    rows.forEach((item, index) => {
      if (typeof item.last81 === "number" && Number.isFinite(item.last81)) {
        meanPoints.push({ x: mapX(index), y: mapY(item.last81) });
      }
    });
    if (meanPoints.length >= 2) {
      ctx.save();
      ctx.setLineDash([5, 4]);
      ctx.strokeStyle = "#f4b860";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      meanPoints.forEach((point, index) => {
        if (index === 0) ctx.moveTo(point.x, point.y);
        else ctx.lineTo(point.x, point.y);
      });
      ctx.stroke();
      ctx.restore();
    }

    const latest = rows[rows.length - 1];
    ctx.fillStyle = "#4dd4c6";
    ctx.beginPath();
    ctx.arc(mapX(rows.length - 1), mapY(latest.flux), 4, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    ctx.font = "12px Segoe UI, sans-serif";
    ctx.fillStyle = "#4dd4c6";
    ctx.fillRect(padding.left, 12, 14, 3);
    ctx.fillText("F10.7 日值", padding.left + 20, 18);
    ctx.fillStyle = "#f4b860";
    ctx.fillRect(padding.left + 122, 12, 14, 3);
    ctx.fillText("81 天均值", padding.left + 142, 18);

    const lastX = mapX(rows.length - 1);
    ctx.fillStyle = "#e7edf5";
    ctx.font = "11px Consolas, monospace";
    const label = formatF107Value(latest.flux);
    ctx.fillText(
      label,
      lastX > width - 70 ? lastX - 42 : lastX + 8,
      mapY(latest.flux) - 9
    );
    canvas.setAttribute(
      "aria-label",
      "F10.7 近半年曲线：" +
        (data.range?.start || "-") +
        " 至 " +
        (data.range?.end || "-") +
        "，最新 " +
        label +
        " sfu"
    );
  }

  function f107SeriesCsv() {
    const series = (state.f107 && state.f107.series) || [];
    const lines = ["date,F10.7_sfu,F10.7_81d_mean_sfu"];
    series.forEach((item) => {
      const values = [item.date || "", item.flux, item.last81].map((value) =>
        typeof value === "number" && Number.isFinite(value)
          ? value.toFixed(1)
          : String(value || "")
      );
      lines.push(values.join(","));
    });
    return lines.join("\n");
  }

  async function copyF107Series() {
    if (!state.f107) return;
    const message = $("#f107Message");
    const ok = await copyText(
      f107SeriesCsv(),
      "已复制近半年 F10.7 曲线数据"
    );
    message.className = ok ? "hint" : "hint error-text";
    message.textContent = ok
      ? "近半年曲线数据已复制（" + (state.f107.series || []).length + " 行）"
      : "复制失败";
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

  function formatApsGroupText(group) {
    if (!group) return "";
    const rows = [
      ["a (km)", "a_km"],
      ["e", "e"],
      ["i (deg)", "i_deg"],
      ["Ω (deg)", "raan_deg"],
      ["ω (deg)", "argp_deg"],
      ["M (deg)", "m_deg"],
    ];
    return rows
      .map(([label, key]) => label + "\t" + formatElement(group[key]))
      .join("\n");
  }

  function apsOutputInfo(mode) {
    return mode === "m2o"
      ? { key: "osculating", label: "瞬根", inputLabel: "平根" }
      : { key: "mean", label: "平根", inputLabel: "瞬根" };
  }

  function updateApsResultDirection(mode) {
    const info = apsOutputInfo(mode);
    const inputHead = $("#apsInputHead");
    const outputHead = $("#apsOutputHead");
    if (inputHead) inputHead.textContent = info.inputLabel + "（输入）";
    if (outputHead) outputHead.textContent = info.label + "（输出）";
    const button = $("#copyAps");
    if (button) button.textContent = "复制" + info.label;
    labelApsResultInputs();
  }

  function clearApsResult() {
    ["A", "E", "I", "Raan", "Argp", "M"].forEach((suffix) => {
      ["In", "Out"].forEach((prefix) => {
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
      return true;
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
        return true;
      } catch (fallbackError) {
        toast("复制失败", true);
        return false;
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
      const info = apsOutputInfo(result.mode);
      fillApsGroup("In", result.input);
      fillApsGroup("Out", result[info.key]);
      updateApsResultDirection(result.mode);
      $("#apsMeta").textContent =
        "模式 " + info.inputLabel + " → " + info.label + " · 历元 " + (result.epoch || "-") +
        (result.end_of_life ? " · 近地点过低" : "");
      $("#copyAps").dataset.text = formatApsGroupText(result[info.key]);
      $("#copyAps").disabled = false;
    } catch (error) {
      $("#apsMeta").textContent = error.message;
      toast(error.message, true);
    } finally {
      submit.disabled = false;
    }
  }

  function renderJ2000Result(result) {
    const rows = [];
    if (result.mode === "rv2el") {
      const el = result.elements || {};
      rows.push(
        ["a (km)", el.a_km, 6],
        ["e", el.e, 9],
        ["i (deg)", el.i_deg, 6],
        ["Ω (deg)", el.raan_deg, 6],
        ["ω (deg)", el.argp_deg, 6],
        ["M (deg)", el.m_deg, 6],
        ["ν (deg)", el.nu_deg, 6],
        ["周期 (min)", el.period_min, 4],
        ["|r| (km)", el.r_norm_km, 6],
        ["|v| (km/s)", el.v_norm_km_s, 9]
      );
    } else {
      const r = result.r_km || [];
      const v = result.v_km_s || [];
      rows.push(
        ["X (km)", r[0], 6],
        ["Y (km)", r[1], 6],
        ["Z (km)", r[2], 6],
        ["VX (km/s)", v[0], 9],
        ["VY (km/s)", v[1], 9],
        ["VZ (km/s)", v[2], 9],
        ["|r| (km)", result.r_norm_km, 6],
        ["|v| (km/s)", result.v_norm_km_s, 9]
      );
    }
    $("#j2000ResultBox").querySelector("tbody").innerHTML = rows
      .map(
        ([label, value, precision]) =>
          '<tr><th scope="row">' + label + "</th><td>" +
          (value === undefined || value === null ? "-" : Number(value).toFixed(precision)) +
          "</td></tr>"
      )
      .join("");
    $("#j2000ResultBox").hidden = false;
    $("#copyJ2000").dataset.text = rows
      .map(([label, value]) => label + "\t" + formatElement(value))
      .join("\n");
    $("#copyJ2000").disabled = false;
  }

  async function submitJ2000(event) {
    event.preventDefault();
    const mode = $("#j2000Mode").value;
    const body = { mode, mu: $("#j2000Mu").value };
    if (mode === "rv2el") {
      body.r_km = ["#j2000X", "#j2000Y", "#j2000Z"].map((id) => $(id).value);
      body.v_km_s = ["#j2000Vx", "#j2000Vy", "#j2000Vz"].map((id) => $(id).value);
    } else {
      body.a_km = $("#j2000A").value;
      body.e = $("#j2000E").value;
      body.i_deg = $("#j2000I").value;
      body.raan_deg = $("#j2000Raan").value;
      body.argp_deg = $("#j2000Argp").value;
      body.m_deg = $("#j2000M").value;
    }
    const submit = $("#j2000Form").querySelector('button[type="submit"]');
    const message = $("#j2000Message");
    submit.disabled = true;
    $("#copyJ2000").disabled = true;
    delete $("#copyJ2000").dataset.text;
    message.className = "hint";
    message.textContent = "计算中...";
    try {
      const data = await api("/api/orbit/convert", {
        method: "POST",
        body,
        timeoutMs: 30000,
      });
      renderJ2000Result(data.result);
      message.textContent = "";
    } catch (error) {
      $("#j2000ResultBox").hidden = true;
      message.className = "hint error-text";
      message.textContent = error.message;
    } finally {
      submit.disabled = false;
    }
  }

  async function copyJ2000Result() {
    const content = $("#copyJ2000").dataset.text;
    if (!content) return;
    await copyText(content, "已复制 J2000 转换结果");
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
      state.tleSamples = samples;
      $("#copyTleRv").disabled = !samples.length;
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

  function tleRvCsv() {
    const header =
      "t_min,UTC,X (km),Y (km),Z (km),VX (km/s),VY (km/s),VZ (km/s)";
    const rows = state.tleSamples.map((sample) =>
      [
        Number(sample.t_min).toFixed(2),
        sample.utc || "",
        ...(sample.r_km || []).map((value) => Number(value).toFixed(3)),
        ...(sample.v_km_s || []).map((value) => Number(value).toFixed(6)),
      ].join(",")
    );
    return [header, ...rows].join("\n");
  }

  async function copyTleRv() {
    if (!state.tleSamples.length) return;
    await copyText(
      tleRvCsv(),
      "已复制地固系 RV 数据（" + state.tleSamples.length + " 行）"
    );
  }

  function savedNoradGroups(data) {
    const ids = Array.isArray(data) ? data : (data && data.norad_ids) || [];
    const groups = (data && data.groups) || {};
    const hasGroups =
      Array.isArray(groups.china) ||
      Array.isArray(groups.foreign) ||
      Array.isArray(groups.unknown);
    return {
      ids,
      china: Array.isArray(groups.china) ? groups.china : [],
      foreign: Array.isArray(groups.foreign)
        ? groups.foreign
        : hasGroups
        ? []
        : ids,
      unknown: Array.isArray(groups.unknown) ? groups.unknown : [],
      states: (data && data.states) || {},
      classification: (data && data.classification) || {},
    };
  }

  function renderSavedNoradGroup(container, ids, states, unknownIds) {
    container.textContent = "";
    if (!ids.length) {
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "暂无";
      container.appendChild(empty);
      return;
    }
    ids.forEach((id) => {
      const isUnknown = unknownIds.has(Number(id));
      const item = document.createElement("div");
      item.className = "norad-saved-item";
      const info = document.createElement("div");
      info.className = "norad-saved-info";
      const value = document.createElement("span");
      value.className = "norad-saved-id";
      value.textContent = id;
      const country = document.createElement("span");
      country.className = isUnknown
        ? "norad-saved-state unknown"
        : "norad-saved-state";
      country.textContent = isUnknown ? "未分类" : states[String(id)] || "—";
      country.title = isUnknown
        ? "GCAT 目录中未找到该 NORAD ID"
        : "GCAT State: " + (states[String(id)] || "未知");
      info.appendChild(value);
      info.appendChild(country);
      const actions = document.createElement("div");
      actions.className = "norad-saved-actions";
      const add = document.createElement("button");
      add.className = "btn ghost";
      add.type = "button";
      add.textContent = "添加";
      add.addEventListener("click", () => appendSavedNoradId(id));
      const remove = document.createElement("button");
      remove.className = "btn ghost danger";
      remove.type = "button";
      remove.textContent = "删除";
      remove.title = "从保存列表和本地文件删除";
      remove.addEventListener("click", () => deleteSavedNoradId(id));
      actions.appendChild(add);
      actions.appendChild(remove);
      item.appendChild(info);
      item.appendChild(actions);
      container.appendChild(item);
    });
  }

  function renderSavedNoradIds(data) {
    const groups = savedNoradGroups(data);
    const unknownIds = new Set(groups.unknown.map(Number));
    $("#noradSavedMeta").textContent = groups.ids.length + " 个";
    $("#noradSavedChinaCount").textContent = groups.china.length;
    $("#noradSavedForeignCount").textContent =
      groups.foreign.length + groups.unknown.length;
    renderSavedNoradGroup(
      $("#noradSavedChina"),
      groups.china,
      groups.states,
      unknownIds
    );
    renderSavedNoradGroup(
      $("#noradSavedForeign"),
      groups.foreign.concat(groups.unknown),
      groups.states,
      unknownIds
    );

    const note = $("#noradSavedNote");
    if (groups.classification.warning) {
      note.className = "hint norad-saved-note warning";
      note.textContent = groups.classification.warning;
    } else if (groups.unknown.length) {
      note.className = "hint norad-saved-note warning";
      note.textContent =
        groups.unknown.length +
        " 个 ID 未匹配 GCAT 国家信息，已归入国外列";
    } else {
      note.className = "hint norad-saved-note";
      note.textContent = "国家分类：GCAT State（CN 为中国）";
    }
  }

  async function loadSavedNoradIds() {
    $("#noradSavedMeta").textContent = "加载中...";
    try {
      const data = await api("/api/norad/saved");
      state.savedNoradIds = data.norad_ids || [];
      renderSavedNoradIds(data);
    } catch (error) {
      $("#noradSavedMeta").textContent = "加载失败";
      const message = $("#queryMessage");
      message.className = "hint error-text";
      message.textContent = "保存列表加载失败：" + error.message;
    }
  }

  async function loadRecentLaunches(force = false) {
    const button = $("#refreshRecentLaunches");
    const list = $("#recentLaunchList");
    const meta = $("#recentLaunchMeta");
    const note = $("#recentLaunchNote");
    if (!list || state.recentLaunchesLoading) return;
    state.recentLaunchesLoading = true;
    if (button) button.disabled = true;
    meta.textContent = "加载中...";
    list.innerHTML = '<p class="hint">加载中...</p>';
    try {
      const data = await api(
        "/api/celestrak/recent-launches" + (force ? "?refresh=1" : ""),
        { timeoutMs: 60000 }
      );
      state.recentLaunches = data;
      state.recentLaunchesAt = Date.now();
      renderRecentLaunches(data);
    } catch (error) {
      state.recentLaunches = null;
      meta.textContent = "加载失败";
      list.innerHTML =
        '<p class="error-text">' + escapeHtml(error.message) + "</p>";
      note.className = "hint norad-saved-note warning";
      note.textContent = "最新发射数据加载失败，请稍后重试";
    } finally {
      state.recentLaunchesLoading = false;
      if (button) button.disabled = false;
    }
  }

  function renderRecentLaunches(data) {
    const list = $("#recentLaunchList");
    const meta = $("#recentLaunchMeta");
    const note = $("#recentLaunchNote");
    const objects = Array.isArray(data.objects) ? data.objects : [];
    list.textContent = "";

    if (!data.launch_date || !objects.length) {
      meta.textContent = "最近 30 天暂无发射记录";
      const empty = document.createElement("p");
      empty.className = "hint";
      empty.textContent = "暂无";
      list.appendChild(empty);
      note.className = "hint norad-saved-note";
      note.textContent = "数据源：CelesTrak SATCAT · 仅显示载荷（PAY）";
      return;
    }

    meta.textContent = data.launch_date + " · " + objects.length + " 颗载荷";

    let unsupported = 0;
    objects.forEach((entry) => {
      if (entry.tle_available === false) unsupported += 1;

      const item = document.createElement("div");
      item.className = "recent-launch-item";

      const info = document.createElement("div");
      info.className = "recent-launch-info";

      const name = document.createElement("span");
      name.className = "recent-launch-name";
      name.textContent = entry.name || "NORAD " + entry.norad_id;
      name.title = name.textContent;

      const ident = document.createElement("span");
      ident.className = "recent-launch-meta";
      ident.textContent =
        "NORAD " + entry.norad_id +
        (entry.object_id ? " · " + entry.object_id : "");

      const detail = document.createElement("span");
      detail.className = "recent-launch-meta";
      const parts = [];
      if (entry.owner) parts.push(entry.owner);
      if (entry.launch_site) parts.push(entry.launch_site);
      parts.push(entry.in_orbit === false ? "已再入" : "在轨");
      detail.textContent = parts.join(" · ");
      detail.title = detail.textContent;

      info.appendChild(name);
      info.appendChild(ident);
      info.appendChild(detail);

      const actions = document.createElement("div");
      actions.className = "recent-launch-actions";
      const add = document.createElement("button");
      add.className = "btn ghost";
      add.type = "button";
      add.textContent = "添加";
      if (entry.tle_available === false) {
        add.disabled = true;
        add.title = "Celestrak TLE 格式不支持 6 位 NORAD ID";
      } else {
        add.addEventListener("click", () => appendSavedNoradId(entry.norad_id));
      }
      actions.appendChild(add);

      item.appendChild(info);
      item.appendChild(actions);
      list.appendChild(item);
    });

    if (data.warning) {
      note.className = "hint norad-saved-note warning";
      note.textContent = data.warning;
    } else if (unsupported) {
      note.className = "hint norad-saved-note warning";
      note.textContent =
        unsupported +
        " 颗 6 位 NORAD ID 暂不支持 TLE 格式，添加按钮不可用";
    } else {
      note.className = "hint norad-saved-note";
      note.textContent = "数据源：CelesTrak SATCAT · 仅显示载荷（PAY）";
    }
  }

  function appendSavedNoradId(id) {
    const input = $("#noradIds");
    const message = $("#queryMessage");
    const current = input.value.split(/[\s,;]+/).filter(Boolean);
    if (current.includes(String(id))) {
      message.className = "hint";
      message.textContent = "NORAD " + id + " 已在查询栏";
      return;
    }
    if (current.length >= 10) {
      message.className = "hint error-text";
      message.textContent = "查询栏最多 10 个 NORAD ID";
      return;
    }
    input.value = input.value.trim()
      ? input.value.trim().replace(/[\s,;]+$/, "") + ", " + id
      : String(id);
    input.focus();
    message.className = "hint";
    message.textContent = "已添加 NORAD " + id;
  }

  async function saveNoradIds() {
    const message = $("#queryMessage");
    const button = $("#saveNorad");
    button.disabled = true;
    try {
      const data = await api("/api/norad/saved", {
        method: "POST",
        body: { norad_ids: $("#noradIds").value },
      });
      state.savedNoradIds = data.norad_ids || [];
      renderSavedNoradIds(data);
      message.className = "hint";
      message.textContent = data.added
        ? "已保存 " + data.added + " 个 NORAD ID"
        : "这些 NORAD ID 已在保存列表中";
    } catch (error) {
      message.className = "hint error-text";
      message.textContent = "保存失败：" + error.message;
    } finally {
      button.disabled = false;
    }
  }

  async function deleteSavedNoradId(id) {
    const message = $("#queryMessage");
    try {
      const data = await api("/api/norad/saved/delete", {
        method: "POST",
        body: { norad_id: id },
      });
      state.savedNoradIds = data.norad_ids || [];
      renderSavedNoradIds(data);
      message.className = data.removed ? "hint" : "hint";
      message.textContent = data.removed
        ? "已删除 NORAD " + id
        : "NORAD " + id + " 不在保存列表中";
    } catch (error) {
      message.className = "hint error-text";
      message.textContent = "删除失败：" + error.message;
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

  function initWalleText() {
    const text = $("#walleText");
    if (!text) return;
    const randomColor = () =>
      "hsl(" + Math.floor(Math.random() * 360) + ", 90%, 65%)";
    text.style.color = randomColor();
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    window.setInterval(() => {
      text.style.color = randomColor();
    }, 3000);
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

  const LAYOUT_STORAGE_KEY = "satelliteTool.layout.v1";

  function readSavedLayout() {
    try {
      const raw = window.localStorage.getItem(LAYOUT_STORAGE_KEY);
      if (!raw) return {};
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function zonePanels(zone) {
    return $$("[data-panel]", zone).filter((panel) => panel.parentElement === zone);
  }

  function panelHandle(panel) {
    return panel.querySelector(".panel-head") || panel.querySelector(".panel-title");
  }

  function saveLayout() {
    const payload = {};
    $$("[data-zone]").forEach((zone) => {
      payload[zone.dataset.zone] = zonePanels(zone).map((panel) => panel.dataset.panel);
    });
    try {
      window.localStorage.setItem(LAYOUT_STORAGE_KEY, JSON.stringify(payload));
    } catch (error) {
      // 本地存储不可用时静默忽略，布局仅在本次会话生效
    }
  }

  function clearDropActive() {
    $$("[data-zone].drop-active").forEach((zone) => zone.classList.remove("drop-active"));
  }

  function onDragStart(event) {
    const handle = event.target.closest(".drag-handle");
    const panel = handle && handle.closest("[data-panel]");
    if (!panel || !panel.parentElement) return;
    state.drag = {
      panel,
      fromZone: panel.parentElement,
      nextSibling: panel.nextElementSibling,
      dropped: false,
    };
    event.dataTransfer.effectAllowed = "move";
    try {
      event.dataTransfer.setData("text/plain", panel.dataset.panel);
    } catch (error) {
      // 个别浏览器可能不允许写入 dataTransfer
    }
    window.setTimeout(() => {
      if (state.drag && state.drag.panel === panel) {
        panel.classList.add("dragging");
      }
    }, 0);
  }

  function onDragOver(event) {
    if (!state.drag) return;
    const zone = event.currentTarget;
    event.preventDefault();
    event.dataTransfer.dropEffect = "move";
    clearDropActive();
    zone.classList.add("drop-active");
    const panel = state.drag.panel;
    const candidates = zonePanels(zone).filter((item) => item !== panel);
    let before = null;
    for (const item of candidates) {
      const rect = item.getBoundingClientRect();
      if (event.clientY < rect.top + rect.height / 2) {
        before = item;
        break;
      }
    }
    if (before) zone.insertBefore(panel, before);
    else zone.appendChild(panel);
  }

  function onDrop(event) {
    if (!state.drag) return;
    event.preventDefault();
    state.drag.dropped = true;
    saveLayout();
  }

  function onDragEnd() {
    const drag = state.drag;
    state.drag = null;
    clearDropActive();
    if (!drag) return;
    drag.panel.classList.remove("dragging");
    if (!drag.dropped) {
      // 未完成放置（在放置区外松开）时还原到原位置
      if (drag.nextSibling && drag.nextSibling !== drag.panel &&
          drag.nextSibling.parentElement === drag.fromZone) {
        drag.fromZone.insertBefore(drag.panel, drag.nextSibling);
      } else {
        drag.fromZone.appendChild(drag.panel);
      }
    }
  }

  function initDraggableLayout() {
    const saved = readSavedLayout();
    $$("[data-zone]").forEach((zone) => {
      const order = Array.isArray(saved[zone.dataset.zone]) ? saved[zone.dataset.zone] : [];
      order.forEach((panelId) => {
        if (typeof panelId !== "string" || !/^[a-z0-9-]+$/.test(panelId)) return;
        const panel = document.querySelector('[data-panel="' + panelId + '"]');
        if (panel) zone.appendChild(panel);
      });
      zonePanels(zone).forEach((panel) => {
        const handle = panelHandle(panel);
        if (!handle) return;
        handle.classList.add("drag-handle");
        handle.draggable = true;
        handle.title = "按住拖动以调整布局";
        handle.addEventListener("dragstart", onDragStart);
        handle.addEventListener("dragend", onDragEnd);
      });
      zone.addEventListener("dragover", onDragOver);
      zone.addEventListener("drop", onDrop);
    });
  }

  function bind() {
    $$(".nav-btn").forEach((button) => {
      button.addEventListener("click", () => switchPage(button.dataset.page));
    });
    $$(".home-shortcut").forEach((button) => {
      button.addEventListener("click", () => switchPage(button.dataset.go));
    });
    $("#dataWarningClose").addEventListener("click", () => {
      $("#dataWarning").classList.add("hidden");
    });
    $("#runSimulation").addEventListener("click", runSimulation);
    $("#stopSimulation").addEventListener("click", stopSimulation);
    $("#profileSelect").addEventListener("change", updateProfileNote);
    $("#chartColumn").addEventListener("change", drawChart);
    $("#refreshJobs").addEventListener("click", loadJobs);
    $("#clearJobs").addEventListener("click", clearJobs);
    $("#scenarioSelect").addEventListener("change", updateScenarioHint);
    $("#apsForm").addEventListener("submit", submitAps);
    $("#apsMode").addEventListener("change", () => {
      updateApsResultDirection($("#apsMode").value);
    });
    $("#j2000Form").addEventListener("submit", submitJ2000);
    $("#copyJ2000").addEventListener("click", copyJ2000Result);
    $("#j2000Mode").addEventListener("change", () => {
      const mode = $("#j2000Mode").value;
      $("#j2000RvFields").hidden = mode !== "rv2el";
      $("#j2000ElFields").hidden = mode !== "el2rv";
      $("#j2000ResultBox").hidden = true;
      $("#copyJ2000").disabled = true;
      delete $("#copyJ2000").dataset.text;
      $("#j2000Message").className = "hint";
      $("#j2000Message").textContent = "";
    });
    $("#copyAps").addEventListener("click", () => {
      const content = $("#copyAps").dataset.text;
      if (content) {
        copyText(content, "已复制" + apsOutputInfo($("#apsMode").value).label + "参数");
      }
    });
    $("#tleForm").addEventListener("submit", submitTle);
    $("#copyTleRv").addEventListener("click", copyTleRv);
    $("#queryTle").addEventListener("click", queryTle);
    $("#saveNorad").addEventListener("click", saveNoradIds);
    $("#refreshRecentLaunches").addEventListener("click", () => loadRecentLaunches(true));
    $("#copyAllTle").addEventListener("click", copyAllTle);
    $("#f107Refresh").addEventListener("click", () => loadF107(true));
    $("#f107Copy").addEventListener("click", copyF107Series);
    updateApsResultDirection($("#apsMode").value);
    window.addEventListener("hashchange", () => {
      const page = pageFromHash();
      const active = $(".page.active");
      if (active?.id !== "page-" + page) switchPage(page, false);
    });
    window.addEventListener("resize", () => {
      drawChart();
      if ($("#page-f107").classList.contains("active") && state.f107) {
        drawF107Chart();
      }
    });
  }

  async function boot() {
    bind();
    initDraggableLayout();
    initWalle();
    initWalleText();
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
