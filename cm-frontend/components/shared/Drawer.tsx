"use client";

import type { ReactNode } from "react";

import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

const WIDTH_CLASS = {
  sm: "data-[side=right]:sm:max-w-sm",
  md: "data-[side=right]:sm:max-w-md",
  lg: "data-[side=right]:sm:max-w-xl",
} as const;

export type DrawerProps = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  subtitle?: string;
  children: ReactNode;
  footer?: ReactNode;
  width?: keyof typeof WIDTH_CLASS;
};

export function Drawer({
  open,
  onOpenChange,
  title,
  subtitle,
  children,
  footer,
  width = "md",
}: DrawerProps) {
  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className={cn(WIDTH_CLASS[width])}>
        <SheetHeader>
          <SheetTitle>{title}</SheetTitle>
          {subtitle ? <SheetDescription>{subtitle}</SheetDescription> : null}
        </SheetHeader>
        <div className="flex-1 overflow-y-auto px-4 pb-4 text-sm">{children}</div>
        {footer ? <SheetFooter className="border-t border-border bg-muted/30">{footer}</SheetFooter> : null}
      </SheetContent>
    </Sheet>
  );
}
