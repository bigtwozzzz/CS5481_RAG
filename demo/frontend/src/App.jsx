import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { HashRouter } from "react-router-dom";
import { AppProvider } from "./context/AppContext";
import AppShell from "./components/layout/AppShell";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster richColors position="top-center" />
      <AppProvider>
        <HashRouter>
          <AppShell />
        </HashRouter>
      </AppProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
