import AppShell from "@/components/AppShell";
import { loadPortfolioReport } from "@/lib/portfolio";
import { loadAllReports } from "@/lib/reports";

export const dynamic = "force-static";

export default async function HomePage() {
  const [reports, portfolio] = await Promise.all([
    loadAllReports(),
    loadPortfolioReport(),
  ]);
  return <AppShell reports={reports} portfolio={portfolio} />;
}
