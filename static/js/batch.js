(function () {
  "use strict";

  // ─── DOM 요소 ───
  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const fileName = document.getElementById("fileName");
  const uploadBtn = document.getElementById("uploadBtn");
  const uploadForm = document.getElementById("uploadForm");

  const addressColSel = document.getElementById("addressCol");
  const yearColSel = document.getElementById("yearCol");
  const ownerColSel = document.getElementById("ownerCol");
  const shareColSel = document.getElementById("shareCol");
  const defaultYearSel = document.getElementById("defaultYear");
  const previewTableWrapper = document.getElementById("previewTableWrapper");
  const previewTable = document.getElementById("previewTable");
  const parseBtn = document.getElementById("parseBtn");

  const splitBanner = document.getElementById("splitBanner");
  const addressCountInfo = document.getElementById("addressCountInfo");
  const addressTableBody = document.getElementById("addressTableBody");
  const downloadCleanedLink = document.getElementById("downloadCleanedLink");
  const startBatchBtn = document.getElementById("startBatchBtn");

  const progressSection = document.getElementById("progressSection");
  const progressText = document.getElementById("progressText");
  const progressCount = document.getElementById("progressCount");
  const progressFill = document.getElementById("progressFill");
  const currentAddress = document.getElementById("currentAddress");
  const completeSection = document.getElementById("completeSection");
  const downloadLink = document.getElementById("downloadLink");
  const errorSection = document.getElementById("errorSection");
  const errorMessage = document.getElementById("errorMessage");

  if (!dropZone) return;

  // ─── 상태 ───
  let uploadId = null;
  let uploadData = null; // { headers, row_count, preview }
  let parsedData = null; // { total, original_rows, split_count, addresses }
  let jobId = null;

  const steps = [
    document.getElementById("step1-upload"),
    document.getElementById("step2-columns"),
    document.getElementById("step3-preview"),
  ];

  // ─── 유틸리티 ───

  function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function showStep(n) {
    steps.forEach(function (el, i) {
      el.style.display = i === n ? "block" : "none";
    });
    errorSection.style.display = "none";
    progressSection.style.display = "none";
    completeSection.style.display = "none";
  }

  function showError(msg) {
    errorMessage.textContent = msg;
    errorSection.style.display = "block";
  }

  // ─── Step 1: 드래그앤드롭 + 파일 업로드 ───

  dropZone.addEventListener("click", function () { fileInput.click(); });

  dropZone.addEventListener("dragover", function (e) {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", function () {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", function (e) {
    e.preventDefault();
    dropZone.classList.remove("dragover");
    if (e.dataTransfer.files.length > 0) {
      fileInput.files = e.dataTransfer.files;
      onFileSelected();
    }
  });

  fileInput.addEventListener("change", onFileSelected);

  function onFileSelected() {
    if (fileInput.files.length > 0) {
      var file = fileInput.files[0];
      fileName.textContent = file.name + " (" + formatSize(file.size) + ")";
      fileName.style.display = "block";
      uploadBtn.disabled = false;
      dropZone.classList.add("has-file");
    }
  }

  uploadForm.addEventListener("submit", async function (e) {
    e.preventDefault();
    if (!fileInput.files.length) return;

    uploadBtn.disabled = true;
    uploadBtn.textContent = "분석 중...";
    errorSection.style.display = "none";
    document.getElementById("uploadProgress").style.display = "block";

    var formData = new FormData();
    formData.append("file", fileInput.files[0]);

    try {
      var resp = await fetch("/batch/upload", { method: "POST", body: formData });
      var data = await resp.json();

      document.getElementById("uploadProgress").style.display = "none";
      if (!resp.ok || data.error) {
        showError(data.error || "업로드 실패");
        uploadBtn.disabled = false;
        uploadBtn.textContent = "파일 분석하기";
        return;
      }

      uploadId = data.upload_id;
      uploadData = data;
      populateColumnSelects(data.headers);
      renderPreviewTable(data.headers, data.preview);
      // 업로드 요약 표시
      var summary = document.getElementById("uploadSummary");
      if (summary) {
        summary.innerHTML = "<strong>" + escapeHtml(fileInput.files[0].name) + "</strong> — " +
          data.headers.length + "개 컬럼, " + data.row_count + "행 데이터" +
          (data.row_count === 0 ? " (데이터가 없습니다)" : "");
      }
      showStep(1);
    } catch (err) {
      document.getElementById("uploadProgress").style.display = "none";
      showError("네트워크 오류: " + err.message);
      uploadBtn.disabled = false;
      uploadBtn.textContent = "파일 분석하기";
    }
  });

  // ─── Step 2: 컬럼 선택 ───

  function populateColumnSelects(headers) {
    addressColSel.innerHTML = '<option value="">-- 주소 컬럼을 선택하세요 --</option>';
    yearColSel.innerHTML = '<option value="">-- 사용 안함 --</option>';
    ownerColSel.innerHTML = '<option value="">-- 사용 안함 --</option>';
    shareColSel.innerHTML = '<option value="">-- 사용 안함 --</option>';

    var addrAutoIdx = -1;
    var yearAutoIdx = -1;
    var ownerAutoIdx = -1;
    var shareAutoIdx = -1;

    var addrKeywords = ["주소", "소재지", "지번", "도로명", "address", "addr", "위치", "소재"];
    var yearKeywords = ["년도", "연도", "year", "기준"];
    var ownerKeywords = ["소유자", "성명", "이름", "name", "owner", "납세자", "권리자", "상속인"];
    var shareKeywords = ["지분", "share", "持分", "비율", "소유비율", "ownership"];

    headers.forEach(function (h, i) {
      var colLetter = String.fromCharCode(65 + (i % 26));
      var label = h ? escapeHtml(h) : "(컬럼 " + colLetter + ")";
      var displayLabel = colLetter + ": " + label;

      [addressColSel, yearColSel, ownerColSel, shareColSel].forEach(function (sel) {
        var opt = document.createElement("option");
        opt.value = i;
        opt.textContent = displayLabel;
        sel.appendChild(opt);
      });

      // 자동 감지
      var lower = (h || "").toLowerCase();
      if (addrAutoIdx < 0) {
        for (var k = 0; k < addrKeywords.length; k++) {
          if (lower.indexOf(addrKeywords[k]) >= 0) { addrAutoIdx = i; break; }
        }
      }
      if (yearAutoIdx < 0) {
        for (var k = 0; k < yearKeywords.length; k++) {
          if (lower.indexOf(yearKeywords[k]) >= 0) { yearAutoIdx = i; break; }
        }
      }
      if (ownerAutoIdx < 0) {
        for (var k = 0; k < ownerKeywords.length; k++) {
          if (lower.indexOf(ownerKeywords[k]) >= 0) { ownerAutoIdx = i; break; }
        }
      }
      if (shareAutoIdx < 0) {
        for (var k = 0; k < shareKeywords.length; k++) {
          if (lower.indexOf(shareKeywords[k]) >= 0) { shareAutoIdx = i; break; }
        }
      }
    });

    if (addrAutoIdx >= 0) addressColSel.value = addrAutoIdx;
    if (yearAutoIdx >= 0) yearColSel.value = yearAutoIdx;
    if (ownerAutoIdx >= 0) ownerColSel.value = ownerAutoIdx;
    if (shareAutoIdx >= 0) shareColSel.value = shareAutoIdx;

    // 주소 컬럼 미선택 시 분석 버튼 비활성화
    updateParseBtn();
  }

  function updateParseBtn() {
    parseBtn.disabled = (addressColSel.value === "");
  }

  addressColSel.addEventListener("change", updateParseBtn);

  function renderPreviewTable(headers, rows) {
    if (!rows || rows.length === 0) {
      previewTableWrapper.style.display = "none";
      return;
    }

    var addrIdx = addressColSel.value !== "" ? parseInt(addressColSel.value, 10) : -1;
    var yearIdx = yearColSel.value !== "" ? parseInt(yearColSel.value, 10) : -1;
    var ownerIdx = ownerColSel.value !== "" ? parseInt(ownerColSel.value, 10) : -1;
    var shareIdx = shareColSel.value !== "" ? parseInt(shareColSel.value, 10) : -1;

    var colStyles = {};
    if (addrIdx >= 0) colStyles[addrIdx] = {th: "background:#dbeafe;color:var(--primary);font-weight:700;", td: "background:#eff6ff;"};
    if (yearIdx >= 0) colStyles[yearIdx] = {th: "background:#f0fdf4;color:var(--success);font-weight:700;", td: "background:#f0fdf4;"};
    if (ownerIdx >= 0) colStyles[ownerIdx] = {th: "background:#fdf2f8;color:#be185d;font-weight:700;", td: "background:#fdf2f8;"};
    if (shareIdx >= 0) colStyles[shareIdx] = {th: "background:#fff7ed;color:var(--warning);font-weight:700;", td: "background:#fff7ed;"};

    var html = "<thead><tr>";
    headers.forEach(function (h, i) {
      var s = colStyles[i] ? ' style="' + colStyles[i].th + '"' : "";
      html += "<th" + s + ">" + escapeHtml(h || "") + "</th>";
    });
    html += "</tr></thead><tbody>";

    rows.forEach(function (row) {
      html += "<tr>";
      row.forEach(function (cell, i) {
        var s = colStyles[i] ? ' style="' + colStyles[i].td + '"' : "";
        html += "<td" + s + ">" + escapeHtml(cell || "") + "</td>";
      });
      html += "</tr>";
    });
    html += "</tbody>";

    previewTable.innerHTML = html;
    previewTableWrapper.style.display = "block";
  }

  // 컬럼 선택 변경 시 미리보기 하이라이트 갱신
  addressColSel.addEventListener("change", function () {
    if (uploadData) renderPreviewTable(uploadData.headers, uploadData.preview);
  });
  yearColSel.addEventListener("change", function () {
    if (uploadData) renderPreviewTable(uploadData.headers, uploadData.preview);
  });
  ownerColSel.addEventListener("change", function () {
    if (uploadData) renderPreviewTable(uploadData.headers, uploadData.preview);
  });
  shareColSel.addEventListener("change", function () {
    if (uploadData) renderPreviewTable(uploadData.headers, uploadData.preview);
  });

  document.getElementById("backToStep1").addEventListener("click", function () {
    uploadBtn.disabled = false;
    uploadBtn.textContent = "파일 분석하기";
    showStep(0);
  });

  parseBtn.addEventListener("click", async function () {
    parseBtn.disabled = true;
    parseBtn.textContent = "분석 중...";
    errorSection.style.display = "none";
    document.getElementById("parseProgress").style.display = "block";

    try {
      var resp = await fetch("/batch/parse", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          upload_id: uploadId,
          address_col: parseInt(addressColSel.value, 10),
          year_col: yearColSel.value !== "" ? parseInt(yearColSel.value, 10) : null,
          owner_col: ownerColSel.value !== "" ? parseInt(ownerColSel.value, 10) : null,
          share_col: shareColSel.value !== "" ? parseInt(shareColSel.value, 10) : null,
          default_year: defaultYearSel.value,
        }),
      });
      var data = await resp.json();

      if (!resp.ok || data.error) {
        showError(data.error || "분석 실패");
        parseBtn.disabled = false;
        parseBtn.textContent = "주소 분석하기";
        return;
      }

      parsedData = data;
      renderParsedAddresses(data);
      showStep(2);
    } catch (err) {
      showError("네트워크 오류: " + err.message);
    } finally {
      document.getElementById("parseProgress").style.display = "none";
      parseBtn.disabled = false;
      parseBtn.textContent = "주소 분석하기";
    }
  });

  // ─── Step 3: 주소 분석 결과 ───

  function renderParsedAddresses(data) {
    addressCountInfo.textContent = "총 " + data.total + "건의 주소가 분석되었습니다.";

    if (data.split_count > 0) {
      splitBanner.textContent =
        "복수 주소가 포함된 셀이 감지되어 " + data.split_count + "건이 분리되었습니다. " +
        "(원본 " + data.original_rows + "행 → " + data.total + "건)";
      splitBanner.style.display = "block";
    } else {
      splitBanner.style.display = "none";
    }

    var hasOwner = data.addresses.some(function (a) { return a.owner; });
    var hasShare = data.addresses.some(function (a) { return a.share_display; });

    // 동적 테이블 헤더
    var headHtml = "<th>#</th>";
    if (hasOwner) headHtml += "<th>소유자</th>";
    headHtml += "<th>주소</th><th>기준년도</th>";
    if (hasShare) headHtml += "<th>지분</th>";
    headHtml += "<th>원본행</th>";
    document.getElementById("addressTableHead").innerHTML = headHtml;

    // 소유자가 있으면 소유자별 정렬
    var sorted = data.addresses.slice();
    if (hasOwner) {
      sorted.sort(function (a, b) {
        var oa = a.owner || "", ob = b.owner || "";
        if (oa < ob) return -1;
        if (oa > ob) return 1;
        return a.original_row - b.original_row;
      });
    }

    var html = "";
    var prevOwner = null;
    sorted.forEach(function (a, i) {
      // 소유자 구분선
      if (hasOwner && a.owner !== prevOwner && prevOwner !== null) {
        var colSpan = 4 + (hasOwner ? 1 : 0) + (hasShare ? 1 : 0);
        html += '<tr><td colspan="' + colSpan + '" style="padding:2px;background:var(--border);"></td></tr>';
      }
      prevOwner = a.owner;

      html += "<tr>";
      html += "<td>" + (i + 1) + "</td>";
      if (hasOwner) html += "<td>" + escapeHtml(a.owner || "") + "</td>";
      html += "<td>" + escapeHtml(a.address) + "</td>";
      html += "<td>" + escapeHtml(a.year || "") + "</td>";
      if (hasShare) html += "<td>" + escapeHtml(a.share_display || "") + "</td>";
      html += "<td>" + a.original_row + "</td>";
      html += "</tr>";
    });
    addressTableBody.innerHTML = html;

    downloadCleanedLink.href = "/batch/download-cleaned/" + uploadId;
  }

  document.getElementById("backToStep2").addEventListener("click", function () {
    showStep(1);
  });

  startBatchBtn.addEventListener("click", async function () {
    startBatchBtn.disabled = true;
    startBatchBtn.textContent = "시작 중...";
    errorSection.style.display = "none";
    document.getElementById("startProgress").style.display = "block";

    try {
      var resp = await fetch("/batch/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ upload_id: uploadId }),
      });
      var data = await resp.json();

      document.getElementById("startProgress").style.display = "none";
      if (!resp.ok || data.error) {
        showError(data.error || "시작 실패");
        startBatchBtn.disabled = false;
        startBatchBtn.textContent = "일괄 조회 시작";
        return;
      }

      jobId = data.job_id;
      steps.forEach(function (el) { el.style.display = "none"; });
      progressSection.style.display = "block";
      pollStatus(jobId);
    } catch (err) {
      document.getElementById("startProgress").style.display = "none";
      showError("네트워크 오류: " + err.message);
      startBatchBtn.disabled = false;
      startBatchBtn.textContent = "일괄 조회 시작";
    }
  });

  // ─── 진행률 폴링 ───

  function pollStatus(jid) {
    var interval = setInterval(async function () {
      try {
        var resp = await fetch("/batch/status/" + jid);
        var data = await resp.json();

        if (data.error && data.status !== "processing") {
          clearInterval(interval);
          showError(data.error);
          return;
        }

        var pct = data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0;
        progressFill.style.width = pct + "%";
        progressCount.textContent = data.processed + " / " + data.total;
        progressText.textContent = "처리 중... (" + pct + "%)";

        if (data.current_address) {
          currentAddress.textContent = "현재: " + data.current_address;
        }

        if (data.status === "completed") {
          clearInterval(interval);
          progressSection.style.display = "none";
          completeSection.style.display = "block";
          downloadLink.href = "/batch/download/" + jid;
        } else if (data.status === "error") {
          clearInterval(interval);
          showError(data.error || "처리 중 오류가 발생했습니다.");
        }
      } catch (err) {
        // 네트워크 오류는 무시하고 재시도
      }
    }, 1000);
  }
})();
