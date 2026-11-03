// The starting point of the website: it puts the App on the page.
// StrictMode is a development helper that warns about common React mistakes; it does nothing in the live website.

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
