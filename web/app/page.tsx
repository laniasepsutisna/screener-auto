import Dashboard from "@/components/Dashboard";
import { loadAllReports } from "@/lib/reports";

export const dynamic = "force-static";

export default async function HomePage() {
  const reports = await loadAllReports();
  return <Dashboard reports={reports} />;
}
