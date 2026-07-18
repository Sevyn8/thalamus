import Link from "next/link";
import { FileQuestion } from "lucide-react";

import { EmptyState } from "@/components/shared/EmptyState";
import { Button } from "@/components/ui/button";

export default function SuperadminNotFound() {
  return (
    <div className="flex min-h-[60vh] items-center justify-center px-6 py-24">
      <div className="flex flex-col items-center gap-6">
        <EmptyState
          icon={<FileQuestion />}
          title="Page not found"
          body="The Superadmin route you're looking for doesn't exist or has moved."
        />
        <Button
          variant="outline"
          render={<Link href="/superadmin/dashboard" />}
          nativeButton={false}
        >
          Back to dashboard
        </Button>
      </div>
    </div>
  );
}
