"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Bell } from "lucide-react";
import { formatDistanceToNow } from "date-fns";

import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useNotifications } from "@/lib/hooks/use-notifications";

export function NotificationsButton() {
  const router = useRouter();
  const q = useNotifications({ limit: 10 });
  const items = q.data?.items ?? [];
  const unread = items.filter((n) => !n.read).length;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Open notifications"
        className="relative inline-flex h-9 w-9 items-center justify-center rounded-md text-muted-foreground hover:bg-accent hover:text-foreground"
      >
        <Bell className="h-4 w-4" />
        {unread > 0 ? (
          <span className="absolute -right-0.5 -top-0.5 inline-flex h-4 min-w-[1rem] items-center justify-center rounded-full bg-destructive px-1 text-[10px] font-semibold text-destructive-foreground">
            {unread}
          </span>
        ) : null}
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-80">
        <div className="px-1.5 py-1 text-xs font-medium text-muted-foreground">
          Notifications
        </div>
        <DropdownMenuSeparator />
        {q.isLoading ? (
          <div className="px-3 py-4 text-xs text-muted-foreground">Loading...</div>
        ) : items.length === 0 ? (
          <div className="px-3 py-4 text-xs text-muted-foreground">
            No notifications yet.
          </div>
        ) : (
          <ul className="max-h-80 overflow-y-auto">
            {items.map((n) => (
              <li key={n.id}>
                <button
                  type="button"
                  onClick={() => router.push(n.deep_link)}
                  className="flex w-full flex-col gap-1 rounded-sm px-2 py-2 text-left transition-colors hover:bg-accent/40"
                >
                  <div className="flex items-start justify-between gap-2">
                    <span className="text-sm font-medium leading-tight">
                      {!n.read ? (
                        <span
                          aria-hidden="true"
                          className="mr-1.5 inline-block h-2 w-2 rounded-full bg-primary align-middle"
                        />
                      ) : null}
                      {n.title}
                    </span>
                    <span className="shrink-0 text-[10px] text-muted-foreground">
                      {formatDistanceToNow(new Date(n.occurred_at), { addSuffix: true })}
                    </span>
                  </div>
                  <p className="text-xs text-muted-foreground">{n.body}</p>
                </button>
              </li>
            ))}
          </ul>
        )}
        <DropdownMenuSeparator />
        <div className="px-2 py-1.5">
          <Link
            href="/notifications"
            className="inline-flex w-full items-center justify-center rounded-md px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent hover:text-foreground"
          >
            View all
          </Link>
        </div>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
