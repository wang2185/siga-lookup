(function () {
  "use strict";

  const dropZone = document.getElementById("dropZone");
  const fileInput = document.getElementById("fileInput");
  const fileName = document.getElementById("fileName");
  const submitBtn = document.getElementById("submitBtn");
  const batchForm = document.getElementById("batchForm");
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

  // 드래그앤드롭
  dropZone.addEventListener("click", () => fileInput.click());

  dropZone.addEventListener("dragover", (e) => {
    e.preventDefault();
    dropZone.classList.add("dragover");
  });

  dropZone.addEventListener("dragleave", () => {
    dropZone.classList.remove("dragover");
  });

  dropZone.addEventListener("drop", (e) => {
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
      const file = fileInput.files[0];
      fileName.textContent = file.name + " (" + formatSize(file.size) + ")";
      fileName.style.display = "block";
      submitBtn.disabled = false;
      dropZone.classList.add("has-file");
    }
  }

  function formatSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + " KB";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  // 제출
  batchForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!fileInput.files.length) return;

    submitBtn.disabled = true;
    submitBtn.textContent = "업로드 중...";
    errorSection.style.display = "none";
    completeSection.style.display = "none";

    const formData = new FormData(batchForm);

    try {
      const resp = await fetch("/batch/upload", { method: "POST", body: formData });
      const data = await resp.json();

      if (!resp.ok || data.error) {
        showError(data.error || "업로드 실패");
        submitBtn.disabled = false;
        submitBtn.textContent = "일괄 조회 시작";
        return;
      }

      // 진행률 폴링 시작
      batchForm.style.display = "none";
      progressSection.style.display = "block";
      pollStatus(data.job_id);
    } catch (err) {
      showError("네트워크 오류: " + err.message);
      submitBtn.disabled = false;
      submitBtn.textContent = "일괄 조회 시작";
    }
  });

  function pollStatus(jobId) {
    const interval = setInterval(async () => {
      try {
        const resp = await fetch("/batch/status/" + jobId);
        const data = await resp.json();

        if (data.error && data.status !== "processing") {
          clearInterval(interval);
          showError(data.error);
          return;
        }

        const pct = data.total > 0 ? Math.round((data.processed / data.total) * 100) : 0;
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
          downloadLink.href = "/batch/download/" + jobId;
        } else if (data.status === "error") {
          clearInterval(interval);
          showError(data.error || "처리 중 오류가 발생했습니다.");
        }
      } catch (err) {
        // 네트워크 오류는 무시하고 재시도
      }
    }, 1000);
  }

  function showError(msg) {
    errorMessage.textContent = msg;
    errorSection.style.display = "block";
  }
})();
