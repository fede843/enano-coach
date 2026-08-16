import { createRoot } from "react-dom/client";
import { QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter } from "react-router-dom";

import App from "./App";
import { createAppQueryClient } from "./queries";

const root = document.getElementById("app");
const queryClient = createAppQueryClient();

if (root) {
  createRoot(root).render(
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  );
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js", { updateViaCache: "none" }).catch(() => {
    // The shell remains usable when a browser declines installation.
  });
}
