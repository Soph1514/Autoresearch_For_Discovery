import React from "react";
import ReactDOM from "react-dom/client";
import "@xyflow/react/dist/style.css";
import "./style.css";
import App from "./App";
import { ResearchProvider } from "./research";
import { HttpResearchClient } from "./http";
const client = new HttpResearchClient();
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ResearchProvider client={client}>
      <App />
    </ResearchProvider>
  </React.StrictMode>,
);
