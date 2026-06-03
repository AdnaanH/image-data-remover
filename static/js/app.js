(function () {
      var els = {
        drop: document.getElementById("drop"),
        file: document.getElementById("file"),
        status: document.getElementById("status"),
        downloads: document.getElementById("downloads"),
        serverMeta: document.getElementById("serverMeta"),
        heroReading: document.getElementById("heroReading"),
        heroSub: document.getElementById("heroSub"),
        queueLabel: document.getElementById("queueLabel"),
        queueMicro: document.getElementById("queueMicro"),
        preserveAlpha: document.getElementById("preserveAlpha"),
        outFormat: document.getElementById("outFormat"),
        quality: document.getElementById("quality"),
        mode: document.getElementById("mode"),
        stripAfterRembg: document.getElementById("stripAfterRembg"),
        exiftoolCheck: document.getElementById("exiftoolCheck"),
        btnRun: document.getElementById("btnRun"),
        btnZip: document.getElementById("btnZip"),
        btnClearQ: document.getElementById("btnClearQ"),
        auditLog: document.getElementById("auditLog"),
        apiKeyInput: document.getElementById("apiKeyInput"),
        saveKey: document.getElementById("saveKey"),
        clearKey: document.getElementById("clearKey"),
        copyCurl: document.getElementById("copyCurl")
      };
      var queued = [];
      var blobUrls = [];
      var maxUploadMb = 25;

      function authHeaders() {
        var key = sessionStorage.getItem("cleanframeApiKey");
        return key ? { Authorization: "Bearer " + key } : {};
      }
      function esc(value) {
        return String(value).replace(/[&<>"']/g, function (ch) {
          return ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch];
        });
      }
      function setStatus(message, tone) {
        els.status.textContent = message || "";
        els.status.className = "status" + (tone ? " " + tone : "");
        audit(message || "Status updated");
      }
      function audit(message) {
        var li = document.createElement("li");
        var now = new Date();
        li.innerHTML = "<time>" + now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) + "</time><span>" + esc(message) + "</span>";
        els.auditLog.prepend(li);
        while (els.auditLog.children.length > 8) els.auditLog.removeChild(els.auditLog.lastChild);
      }
      function fmtBytes(value) {
        var n = Number(value);
        if (!Number.isFinite(n)) return "unknown size";
        if (n < 1024) return n + " B";
        if (n < 1048576) return (n / 1024).toFixed(1) + " KB";
        return (n / 1048576).toFixed(2) + " MB";
      }
      function clearDownloads() {
        blobUrls.forEach(function (url) { URL.revokeObjectURL(url); });
        blobUrls = [];
        els.downloads.innerHTML = "";
      }
      function updateQueue() {
        var total = queued.reduce(function (sum, file) { return sum + file.size; }, 0);
        if (!queued.length) {
          els.queueLabel.textContent = "No files queued";
          els.queueMicro.textContent = "Choose images to begin.";
          return;
        }
        els.queueLabel.innerHTML = "<span>" + queued.length + "</span> file" + (queued.length === 1 ? "" : "s") + " queued";
        els.queueMicro.textContent = fmtBytes(total) + " selected. Per-file limit: " + maxUploadMb + " MB.";
      }
      function syncMode() {
        var strip = els.mode.value === "strip";
        document.querySelectorAll(".strip-only").forEach(function (node) { node.hidden = !strip; });
        document.querySelectorAll(".nobg-only").forEach(function (node) { node.hidden = strip; });
        els.btnZip.disabled = !strip;
      }
      function renderMeta(data) {
        if (!data || !data.ok) {
          els.serverMeta.innerHTML = '<span class="chip">Offline</span>';
          els.heroReading.textContent = "Offline";
          els.heroSub.textContent = "The API is not reachable from this page.";
          return;
        }
        maxUploadMb = Number(data.max_upload_mb) || 25;
        var chips = [
          ["Max", data.max_upload_mb + " MB"],
          ["ZIP", data.max_zip_total_mb + " MB"],
          ["Batch", data.max_batch_files],
          ["Auth", data.auth_required ? "Required" : "Open"],
          ["Cut-out", data.background_removal ? "Ready" : "Off"],
          ["ExifTool", data.exiftool ? "Ready" : "Off"]
        ];
        els.serverMeta.innerHTML = chips.map(function (pair) {
          return '<span class="chip"><b>' + esc(pair[0]) + '</b>' + esc(pair[1]) + '</span>';
        }).join("");
        els.heroReading.textContent = data.auth_required ? "Locked" : "Local";
        els.heroSub.textContent = "Version " + data.version + ". Uploads are limited and temporary files are removed after each response.";
        updateQueue();
      }
      function addFiles(list) {
        queued = Array.prototype.slice.call(list || []).filter(function (file) { return file && file.size; });
        clearDownloads();
        updateQueue();
        if (queued.length) setStatus("Queue ready. Choose a processing action.", "");
      }
      function queryForStrip() {
        return new URLSearchParams({
          preserve_alpha: els.preserveAlpha.checked ? "true" : "false",
          output: els.outFormat.value,
          quality: String(Math.min(100, Math.max(1, Number(els.quality.value) || 95))),
          exiftool_check: els.exiftoolCheck.checked ? "true" : "false"
        });
      }
      function filenameFromResponse(response, fallback) {
        var cd = response.headers.get("Content-Disposition") || "";
        var match = /filename="?([^";]+)"?/i.exec(cd);
        return match ? match[1] : fallback;
      }
      function addDownload(blob, name, detail) {
        var url = URL.createObjectURL(blob);
        blobUrls.push(url);
        var link = document.createElement("a");
        link.href = url;
        link.download = name;
        link.className = "download";
        link.innerHTML = '<span class="dot">OK</span><span><strong>' + esc(name) + '</strong><small>' + esc(detail || "Download ready") + '</small></span><span class="secondary">Save</span>';
        els.downloads.appendChild(link);
      }
      function parseError(response) {
        return response.json().then(function (body) {
          return body.detail || response.statusText || "Request failed.";
        }).catch(function () {
          return response.statusText || "Request failed.";
        });
      }
      function processOne(file, index, total) {
        if (file.size > maxUploadMb * 1048576) {
          setStatus("Too large: " + file.name, "err");
          return Promise.resolve(false);
        }
        var prefix = total > 1 ? "[" + (index + 1) + "/" + total + "] " : "";
        var isStrip = els.mode.value === "strip";
        var form = new FormData();
        form.append("file", file);
        var query = isStrip ? queryForStrip() : new URLSearchParams({
          strip_metadata: els.stripAfterRembg.checked ? "true" : "false",
          exiftool_check: els.exiftoolCheck.checked ? "true" : "false"
        });
        var url = isStrip ? "/api/strip?" + query : "/api/remove-bg?" + query;
        setStatus(prefix + "Processing " + file.name + "...", "");
        return fetch(url, { method: "POST", headers: authHeaders(), body: form }).then(function (response) {
          if (response.status === 401) {
            setStatus(prefix + "API key required or invalid.", "err");
            return false;
          }
          if (!response.ok) {
            return parseError(response).then(function (message) {
              setStatus(prefix + message, response.status === 501 ? "warn" : "err");
              return false;
            });
          }
          return response.blob().then(function (blob) {
            var name = filenameFromResponse(response, file.name.replace(/(\.[^.]+)?$/, "_clean$1"));
            var detail = fmtBytes(response.headers.get("X-Input-Bytes")) + " to " + fmtBytes(response.headers.get("X-Output-Bytes"));
            var exif = response.headers.get("X-Exiftool-Summary");
            if (exif) detail += " | " + exif;
            addDownload(blob, name, detail);
            setStatus(prefix + "Finished " + file.name, response.headers.get("X-Metadata-Remaining") === "true" ? "warn" : "ok");
            return true;
          });
        }).catch(function () {
          setStatus(prefix + "Network error while processing " + file.name, "err");
          return false;
        });
      }
      function processQueue() {
        if (!queued.length) {
          setStatus("Queue is empty.", "err");
          return;
        }
        clearDownloads();
        var index = 0;
        var ok = 0;
        function next() {
          if (index >= queued.length) {
            setStatus("Batch finished: " + ok + "/" + queued.length + " succeeded.", ok === queued.length ? "ok" : ok ? "warn" : "err");
            return;
          }
          processOne(queued[index], index, queued.length).then(function (result) {
            if (result) ok += 1;
            index += 1;
            next();
          });
        }
        next();
      }
      function processZip() {
        if (!queued.length) {
          setStatus("Queue is empty.", "err");
          return;
        }
        if (els.mode.value !== "strip") {
          setStatus("ZIP mode is available for metadata stripping.", "warn");
          return;
        }
        clearDownloads();
        var form = new FormData();
        queued.forEach(function (file) { form.append("files", file); });
        setStatus("Building batch ZIP...", "");
        fetch("/api/strip-zip?" + queryForStrip(), { method: "POST", headers: authHeaders(), body: form }).then(function (response) {
          if (response.status === 401) {
            setStatus("API key required or invalid.", "err");
            return;
          }
          if (!response.ok) {
            return parseError(response).then(function (message) { setStatus(message, "err"); });
          }
          return response.blob().then(function (blob) {
            addDownload(blob, "cleanframe_batch.zip", "Includes manifest.json audit metadata");
            setStatus("ZIP ready with manifest.", "ok");
          });
        }).catch(function () {
          setStatus("Network error while building ZIP.", "err");
        });
      }

      els.mode.addEventListener("change", syncMode);
      els.file.addEventListener("change", function () { addFiles(els.file.files); els.file.value = ""; });
      ["dragenter", "dragover"].forEach(function (eventName) {
        els.drop.addEventListener(eventName, function (event) {
          event.preventDefault();
          els.drop.classList.add("dragover");
        });
      });
      ["dragleave", "drop"].forEach(function (eventName) {
        els.drop.addEventListener(eventName, function (event) {
          event.preventDefault();
          els.drop.classList.remove("dragover");
        });
      });
      els.drop.addEventListener("drop", function (event) { addFiles(event.dataTransfer.files); });
      els.drop.addEventListener("keydown", function (event) {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          els.file.click();
        }
      });
      els.btnRun.addEventListener("click", processQueue);
      els.btnZip.addEventListener("click", processZip);
      els.btnClearQ.addEventListener("click", function () {
        queued = [];
        clearDownloads();
        updateQueue();
        setStatus("Queue cleared.", "");
      });
      els.saveKey.addEventListener("click", function () {
        var key = els.apiKeyInput.value.trim();
        if (key) sessionStorage.setItem("cleanframeApiKey", key);
        setStatus(key ? "API key saved for this browser session." : "No API key entered.", key ? "ok" : "warn");
      });
      els.clearKey.addEventListener("click", function () {
        sessionStorage.removeItem("cleanframeApiKey");
        els.apiKeyInput.value = "";
        setStatus("Session API key cleared.", "ok");
      });
      els.copyCurl.addEventListener("click", function () {
        var command = 'curl -X POST "http://127.0.0.1:8765/api/strip?output=png&exiftool_check=false" -F "file=@photo.jpg" -o photo_clean.png';
        navigator.clipboard.writeText(command).then(function () {
          setStatus("Example API call copied.", "ok");
        }).catch(function () {
          setStatus(command, "warn");
        });
      });

      var savedKey = sessionStorage.getItem("cleanframeApiKey");
      if (savedKey) els.apiKeyInput.value = savedKey;
      fetch("/health").then(function (response) { return response.json(); }).then(renderMeta).catch(function () { renderMeta(null); });
      syncMode();
      updateQueue();
    })();

