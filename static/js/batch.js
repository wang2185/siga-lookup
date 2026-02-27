(function () {
  "use strict";

  // ─── CSRF 토큰 ───
  var csrfToken = (document.querySelector('meta[name="csrf-token"]') || {}).content || "";

  // ─── DOM 요소 ───
  var dropZone = document.getElementById("dropZone");
  var fileInput = document.getElementById("fileInput");
  var fileName = document.getElementById("fileName");
  var uploadBtn = document.getElementById("uploadBtn");
  var uploadForm = document.getElementById("uploadForm");

  // 버튼 클릭 선택 그룹 + hidden input
  var addressColGroup = document.getElementById("addressColGroup");
  var addressColInput = document.getElementById("addressCol");
  var ownerColGroup = document.getElementById("ownerColGroup");
  var ownerColInput = document.getElementById("ownerCol");
  var shareColGroup = document.getElementById("shareColGroup");
  var shareColInput = document.getElementById("shareCol");
  var yearColGroup = document.getElementById("yearColGroup");
  var yearColInput = document.getElementById("yearCol");
  var defaultYearGroup = document.getElementById("defaultYearGroup");
  var defaultYearInput = document.getElementById("defaultYear");

  var previewTableWrapper = document.getElementById("previewTableWrapper");
  var previewTable = document.getElementById("previewTable");
  var parseBtn = document.getElementById("parseBtn");

  var splitBanner = document.getElementById("splitBanner");
  var addressCountInfo = document.getElementById("addressCountInfo");
  var addressTableBody = document.getElementById("addressTableBody");
  var downloadCleanedLink = document.getElementById("downloadCleanedLink");
  var downloadCleanedLinkTop = document.getElementById("downloadCleanedLinkTop");
  var startBatchBtn = document.getElementById("startBatchBtn");
  var startBatchBtnTop = document.getElementById("startBatchBtnTop");
  var cancelBtn = document.getElementById("cancelBtn");
  var pdfNamePatternInput = document.getElementById("pdfNamePattern");
  var pdfNamePreview = document.getElementById("pdfNamePreview");

  var progressSection = document.getElementById("progressSection");
  var progressText = document.getElementById("progressText");
  var progressCount = document.getElementById("progressCount");
  var progressFill = document.getElementById("progressFill");
  var currentAddress = document.getElementById("currentAddress");
  var completeSection = document.getElementById("completeSection");
  var downloadLink = document.getElementById("downloadLink");
  var downloadExcelLink = document.getElementById("downloadExcelLink");
  var errorSection = document.getElementById("errorSection");
  var errorMessage = document.getElementById("errorMessage");

  if (!dropZone) return;

  // ─── 상태 ───
  var uploadId = null;
  var uploadData = null;
  var parsedData = null;
  var jobId = null;
  var pollInterval = null;

  var steps = [
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

  // ─── 버튼 클릭 선택 그룹 핸들링 ───

  function initBtnSelectGroup(groupEl, inputEl, onChange) {
    if (!groupEl) return;
    groupEl.addEventListener("click", function (e) {
      var btn = e.target.closest(".btn-select");
      if (!btn || btn.classList.contains("disabled")) return;

      // 같은 그룹 내 active 해제
      groupEl.querySelectorAll(".btn-select").forEach(function (b) {
        b.classList.remove("active");
      });
      btn.classList.add("active");
      inputEl.value = btn.getAttribute("data-value") || "";
      if (onChange) onChange();
    });
  }

  // 기본년도 그룹은 이미 HTML에 버튼이 있으므로 바로 바인딩
  initBtnSelectGroup(defaultYearGroup, defaultYearInput);

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
      var resp = await fetch("/batch/upload", {
        method: "POST",
        headers: { "X-CSRFToken": csrfToken },
        body: formData,
      });
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
      populateColumnButtons(data.headers);
      renderPreviewTable(data.headers, data.preview);

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

  // ─── Step 2: 컬럼 선택 (버튼 클릭식) ───

  function populateColumnButtons(headers) {
    var groups = [
      { group: addressColGroup, input: addressColInput, noDefault: true },
      { group: ownerColGroup, input: ownerColInput, noDefault: false },
      { group: shareColGroup, input: shareColInput, noDefault: false },
      { group: yearColGroup, input: yearColInput, noDefault: false },
    ];

    var addrKeywords = ["주소", "소재지", "지번", "도로명", "address", "addr", "위치", "소재"];
    var yearKeywords = ["년도", "연도", "year", "기준"];
    var ownerKeywords = ["소유자", "성명", "이름", "name", "owner", "납세자", "권리자", "상속인"];
    var shareKeywords = ["지분", "share", "持分", "비율", "소유비율", "ownership"];

    var autoDetect = { address: -1, year: -1, owner: -1, share: -1 };
    var keywordSets = [
      { key: "address", keywords: addrKeywords },
      { key: "year", keywords: yearKeywords },
      { key: "owner", keywords: ownerKeywords },
      { key: "share", keywords: shareKeywords },
    ];

    headers.forEach(function (h, i) {
      var lower = (h || "").toLowerCase();
      keywordSets.forEach(function (ks) {
        if (autoDetect[ks.key] < 0) {
          for (var k = 0; k < ks.keywords.length; k++) {
            if (lower.indexOf(ks.keywords[k]) >= 0) {
              autoDetect[ks.key] = i;
              break;
            }
          }
        }
      });
    });

    var autoMap = [autoDetect.address, autoDetect.owner, autoDetect.share, autoDetect.year];

    groups.forEach(function (g, gi) {
      g.group.innerHTML = "";
      g.input.value = "";

      // "사용 안함" 버튼 (주소 컬럼은 제외)
      if (!g.noDefault) {
        var noneBtn = document.createElement("button");
        noneBtn.type = "button";
        noneBtn.className = "btn-select active";
        noneBtn.setAttribute("data-value", "");
        noneBtn.textContent = "사용 안함";
        g.group.appendChild(noneBtn);
      }

      headers.forEach(function (h, i) {
        var colLetter = String.fromCharCode(65 + (i % 26));
        var label = h ? escapeHtml(h) : "(컬럼 " + colLetter + ")";
        var displayLabel = colLetter + ": " + label;

        var btn = document.createElement("button");
        btn.type = "button";
        btn.className = "btn-select";
        btn.setAttribute("data-value", String(i));
        btn.textContent = displayLabel;

        // 자동 선택
        if (autoMap[gi] === i) {
          btn.classList.add("active");
          g.input.value = String(i);
          // "사용 안함" 버튼 비활성화
          var noneB = g.group.querySelector('.btn-select[data-value=""]');
          if (noneB) noneB.classList.remove("active");
        }

        g.group.appendChild(btn);
      });
    });

    // 이벤트 바인딩 — 컬럼 선택 변경 시 미리보기 갱신
    var onColChange = function () {
      if (uploadData) renderPreviewTable(uploadData.headers, uploadData.preview);
      updateParseBtn();
      updatePdfPreview();
    };

    initBtnSelectGroup(addressColGroup, addressColInput, onColChange);
    initBtnSelectGroup(ownerColGroup, ownerColInput, onColChange);
    initBtnSelectGroup(shareColGroup, shareColInput, onColChange);
    initBtnSelectGroup(yearColGroup, yearColInput, onColChange);

    updateParseBtn();
  }

  function updateParseBtn() {
    parseBtn.disabled = (addressColInput.value === "");
  }

  function renderPreviewTable(headers, rows) {
    if (!rows || rows.length === 0) {
      previewTableWrapper.style.display = "none";
      return;
    }

    var addrIdx = addressColInput.value !== "" ? parseInt(addressColInput.value, 10) : -1;
    var yearIdx = yearColInput.value !== "" ? parseInt(yearColInput.value, 10) : -1;
    var ownerIdx = ownerColInput.value !== "" ? parseInt(ownerColInput.value, 10) : -1;
    var shareIdx = shareColInput.value !== "" ? parseInt(shareColInput.value, 10) : -1;

    var colStyles = {};
    if (addrIdx >= 0) colStyles[addrIdx] = { th: "background:#dbeafe;color:var(--primary);font-weight:700;", td: "background:#eff6ff;" };
    if (yearIdx >= 0) colStyles[yearIdx] = { th: "background:#f0fdf4;color:var(--success);font-weight:700;", td: "background:#f0fdf4;" };
    if (ownerIdx >= 0) colStyles[ownerIdx] = { th: "background:#fdf2f8;color:#be185d;font-weight:700;", td: "background:#fdf2f8;" };
    if (shareIdx >= 0) colStyles[shareIdx] = { th: "background:#fff7ed;color:var(--warning);font-weight:700;", td: "background:#fff7ed;" };

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
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({
          upload_id: uploadId,
          address_col: parseInt(addressColInput.value, 10),
          year_col: yearColInput.value !== "" ? parseInt(yearColInput.value, 10) : null,
          owner_col: ownerColInput.value !== "" ? parseInt(ownerColInput.value, 10) : null,
          share_col: shareColInput.value !== "" ? parseInt(shareColInput.value, 10) : null,
          default_year: defaultYearInput.value,
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
    if (downloadCleanedLinkTop) downloadCleanedLinkTop.href = "/batch/download-cleaned/" + uploadId;

    updatePdfPreview();
  }

  // PDF 파일명 미리보기
  function updatePdfPreview() {
    if (!pdfNamePatternInput || !pdfNamePreview) return;
    var pattern = pdfNamePatternInput.value || "{번호}_{소유자}_{주소}";
    var sample = pattern
      .replace("{번호}", "1")
      .replace("{소유자}", "홍길동")
      .replace("{주소}", "서울 강남구 역삼동 601")
      .replace("{년도}", "2025")
      .replace("{지분}", "1/2");
    pdfNamePreview.textContent = "미리보기: " + sample + ".pdf";
  }

  if (pdfNamePatternInput) {
    pdfNamePatternInput.addEventListener("input", updatePdfPreview);
    updatePdfPreview();
  }

  // 뒤로가기 (Step 3 → Step 2)
  document.getElementById("backToStep2").addEventListener("click", function () {
    showStep(1);
  });
  var backToStep2Top = document.getElementById("backToStep2Top");
  if (backToStep2Top) {
    backToStep2Top.addEventListener("click", function () {
      showStep(1);
    });
  }

  // 일괄 조회 시작
  async function doStartBatch() {
    startBatchBtn.disabled = true;
    startBatchBtn.textContent = "시작 중...";
    if (startBatchBtnTop) {
      startBatchBtnTop.disabled = true;
      startBatchBtnTop.textContent = "시작 중...";
    }
    errorSection.style.display = "none";
    document.getElementById("startProgress").style.display = "block";

    var pdfPattern = pdfNamePatternInput ? pdfNamePatternInput.value : "{번호}_{소유자}_{주소}";

    try {
      var resp = await fetch("/batch/start", {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken },
        body: JSON.stringify({
          upload_id: uploadId,
          pdf_name_pattern: pdfPattern,
        }),
      });
      var data = await resp.json();

      document.getElementById("startProgress").style.display = "none";
      if (!resp.ok || data.error) {
        showError(data.error || "시작 실패");
        resetStartBtns();
        return;
      }

      jobId = data.job_id;
      steps.forEach(function (el) { el.style.display = "none"; });
      progressSection.style.display = "block";
      cancelBtn.style.display = "block";
      cancelBtn.disabled = false;
      cancelBtn.textContent = "조회 중지";
      pollStatus(jobId);
    } catch (err) {
      document.getElementById("startProgress").style.display = "none";
      showError("네트워크 오류: " + err.message);
      resetStartBtns();
    }
  }

  function resetStartBtns() {
    startBatchBtn.disabled = false;
    startBatchBtn.textContent = "일괄 조회 시작";
    if (startBatchBtnTop) {
      startBatchBtnTop.disabled = false;
      startBatchBtnTop.textContent = "일괄 조회 시작";
    }
  }

  startBatchBtn.addEventListener("click", doStartBatch);
  if (startBatchBtnTop) startBatchBtnTop.addEventListener("click", doStartBatch);

  // ─── 취소 버튼 ───

  if (cancelBtn) {
    cancelBtn.addEventListener("click", async function () {
      if (!jobId) return;
      cancelBtn.disabled = true;
      cancelBtn.textContent = "중지 요청 중...";
      try {
        await fetch("/batch/cancel/" + jobId, {
          method: "POST",
          headers: { "X-CSRFToken": csrfToken },
        });
      } catch (err) {
        // 네트워크 오류 무시
      }
    });
  }

  // ─── 진행률 폴링 ───

  function pollStatus(jid) {
    pollInterval = setInterval(async function () {
      try {
        var resp = await fetch("/batch/status/" + jid);
        var data = await resp.json();

        if (data.error && data.status !== "processing" && data.status !== "cancelled") {
          clearInterval(pollInterval);
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
          clearInterval(pollInterval);
          progressSection.style.display = "none";
          completeSection.style.display = "block";
          var completeMsg = document.getElementById("completeMessage");
          if (completeMsg) {
            completeMsg.innerHTML = "<strong>조회 완료!</strong> " +
              data.processed + "/" + data.total + "건 처리됨. 아래 버튼을 클릭하여 결과를 다운로드하세요.";
          }
          downloadLink.href = "/batch/download/" + jid;
          if (downloadExcelLink) downloadExcelLink.href = "/batch/download-excel/" + jid;
        } else if (data.status === "cancelled") {
          clearInterval(pollInterval);
          progressSection.style.display = "none";
          if (data.has_output) {
            completeSection.style.display = "block";
            var completeMsg = document.getElementById("completeMessage");
            if (completeMsg) {
              completeMsg.innerHTML = "<strong>조회 중지됨.</strong> " +
                data.processed + "/" + data.total + "건까지 처리된 결과를 다운로드할 수 있습니다.";
            }
            downloadLink.href = "/batch/download/" + jid;
            if (downloadExcelLink) downloadExcelLink.href = "/batch/download-excel/" + jid;
          } else {
            showError(data.error || "작업이 취소되었습니다.");
          }
        } else if (data.status === "error") {
          clearInterval(pollInterval);
          showError(data.error || "처리 중 오류가 발생했습니다.");
        }
      } catch (err) {
        // 네트워크 오류는 무시하고 재시도
      }
    }, 1000);
  }
})();
