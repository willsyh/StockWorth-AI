import { Link } from "react-router-dom";
import { Compass } from "lucide-react";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/states";

export default function NotFoundPage() {
  return (
    <EmptyState
      icon={Compass}
      title="Halaman tidak ditemukan"
      description="Alamat yang Anda buka tidak tersedia."
      action={
        <Button asChild variant="outline">
          <Link to="/">Kembali ke Dashboard</Link>
        </Button>
      }
    />
  );
}
