"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";
import { useTheme } from "next-themes";
import { LogOut, HelpCircle, User as UserIcon } from "lucide-react";

import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { setAuthSnapshot, useAuthSnapshot } from "@/lib/auth/auth-cache";
import { clearCurrentPersona } from "@/lib/auth/getAuthToken";
import type { Persona } from "@/lib/auth/personas";

function initialsOf(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

// Phase 5f.W.1: per-user role display deferred until /api/v1/role-
// assignments?user_id={me} wires (Phase 5f.Z.x or later). For now,
// show the userType from the JWT (PLATFORM admin vs Tenant member).
// Role-name specificity returns when role-assignments is consumed.
function userTypeLabel(persona: Persona): string {
  return persona.userType === "PLATFORM" ? "Platform admin" : "Tenant member";
}

export function UserMenu() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const snapshot = useAuthSnapshot();
  const user = snapshot?.user;
  const { theme, setTheme } = useTheme();

  function logout() {
    clearCurrentPersona();
    setAuthSnapshot(null);
    queryClient.clear();
    router.replace("/dev/login");
  }

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Open profile menu"
        className="rounded-full outline-none ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
      >
        <Avatar className="h-9 w-9">
          <AvatarFallback className="bg-primary text-primary-foreground text-xs font-semibold">
            {user ? initialsOf(user.name) : "··"}
          </AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        {user ? (
          <div className="flex flex-col gap-0.5 px-1.5 py-1 text-xs font-medium text-muted-foreground">
            <span className="font-medium text-foreground">{user.name}</span>
            <span className="text-xs font-normal text-muted-foreground">{userTypeLabel(user)}</span>
          </div>
        ) : (
          <div className="px-1.5 py-1 text-xs font-medium text-muted-foreground">
            Loading...
          </div>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem render={<Link href="/profile" />}>
          <UserIcon className="mr-2 h-4 w-4" /> Profile
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <div className="px-1.5 py-1 text-xs font-medium text-muted-foreground">
          Theme
        </div>
        <DropdownMenuRadioGroup
          value={theme ?? "system"}
          onValueChange={(v) => setTheme(v)}
        >
          <DropdownMenuRadioItem value="light">Light</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark">Dark</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system">System</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem disabled>
          <HelpCircle className="mr-2 h-4 w-4" /> Help
        </DropdownMenuItem>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={logout}>
          <LogOut className="mr-2 h-4 w-4" /> Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
