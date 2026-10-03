import React from "react";
import ReactDOM from "react-dom/client";
import "@xyflow/react/dist/style.css";
import "./style.css";
import App from "./App";
import { ResearchProvider } from "./research";
import { MockResearchClient } from "./mock";
const client = new MockResearchClient(2600);
if (import.meta.hot) import.meta.hot.dispose(() => client.dispose());
ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ResearchProvider client={client}>
      <App />
    </ResearchProvider>
  </React.StrictMode>,
);
