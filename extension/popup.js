// popup.js - Live connection status checking for Truss local proxy.

document.addEventListener("DOMContentLoaded", async function() {
  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");

  try {
    const resp = await fetch("http://localhost:8000/healthz");
    if (resp.ok) {
      dot.className = "dot connected";
      text.textContent = "CONNECTED (Port 8000)";
      text.style.color = "var(--sys-color-status-ok)";
    } else {
      throw new Error();
    }
  } catch (e) {
    dot.className = "dot disconnected";
    text.textContent = "UNREACHABLE";
    text.style.color = "var(--sys-color-status-err)";
  }
});
