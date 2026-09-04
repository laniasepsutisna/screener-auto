import Dashboard from "@/components/Dashboard";
import { loadAllReports } from "@/lib/reports";

export const dynamic = "force-static";

export default function HomePage() {
  const reports = loadAllReports();
  return <Dashboard reports={reports} />;
}
