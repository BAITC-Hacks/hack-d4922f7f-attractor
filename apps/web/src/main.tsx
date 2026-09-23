import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./presentation/App";
import "./presentation/styles.css";

// Keep the approved preview as the landing screen and the working V1 calculator accessible.
if (new URLSearchParams(window.location.search).get("mode") === "v1") {
  createRoot(document.getElementById("root")!).render(<StrictMode><App /></StrictMode>);
} else {
  window.location.replace("/design-v2/index.html");
}
