"use client";

import { useState } from "react";
import { Building2, Inbox } from "lucide-react";

import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/shared/EmptyState";
import { Skeleton } from "@/components/shared/Skeleton";
import { Modal } from "@/components/shared/Modal";
import { Drawer } from "@/components/shared/Drawer";
import { ConfirmDialog } from "@/components/shared/ConfirmDialog";
import { ConfirmDestructive } from "@/components/shared/ConfirmDestructive";
import { toast } from "sonner";
import { PageHeader } from "@/components/shared/PageHeader";
import { comingInV1 } from "@/components/shared/ComingInV1Toast";
import {
  ActionChip,
  ResultChip,
  ScopeChip,
  StatusChip,
  TierChip,
} from "@/components/shared/Chips";

function Section({ title, caption, children }: { title: string; caption?: string; children: React.ReactNode }) {
  return (
    <section className="border-b border-border px-12 py-10">
      <h2 className="text-lg font-semibold tracking-tight">{title}</h2>
      {caption ? <p className="mt-1 text-sm text-muted-foreground">{caption}</p> : null}
      <div className="mt-6">{children}</div>
    </section>
  );
}

export default function ComponentsDemoPage() {
  const [modalOpen, setModalOpen] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [destructiveOpen, setDestructiveOpen] = useState(false);
  const [typeConfirmOpen, setTypeConfirmOpen] = useState(false);

  return (
    <div className="min-h-screen">
      <PageHeader
        title="Shared primitives"
        subtitle="Step 1.5 demo. Not linked from chrome. Visit /dev/components."
        primaryAction={{ label: "Demo CTA" }}
      />

      <Section title="PageHeader (above)" caption="Click 'Demo CTA' to see comingInV1() in action.">
        <Button onClick={() => comingInV1()}>Toast: bare comingInV1()</Button>
        <Button className="ml-3" onClick={() => comingInV1("Provision tenant")}>
          Toast: comingInV1(&quot;Provision tenant&quot;)
        </Button>
      </Section>

      <Section title="EmptyState" caption="Used when a list returns zero items.">
        <div className="grid gap-6 md:grid-cols-2">
          <EmptyState
            icon={<Building2 />}
            title="No tenants match your filter"
            body="Try a different search or filter."
          />
          <EmptyState
            icon={<Inbox />}
            title="Approvals inbox coming in v1"
            body="Pending approval requests will appear here when wired."
            action={{ label: "Try CTA", onClick: () => comingInV1("Try CTA") }}
          />
        </div>
      </Section>

      <Section title="Skeleton variants">
        <div className="grid gap-6 md:grid-cols-2">
          <div>
            <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">card × 2</p>
            <div className="grid grid-cols-2 gap-3">
              <Skeleton variant="card" />
              <Skeleton variant="card" />
            </div>
          </div>
          <div>
            <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">row × 4</p>
            <Skeleton variant="row" count={4} />
          </div>
          <div>
            <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">circle</p>
            <Skeleton variant="circle" />
          </div>
          <div>
            <p className="mb-2 text-xs uppercase tracking-wider text-muted-foreground">text × 3</p>
            <Skeleton variant="text" count={3} />
          </div>
        </div>
      </Section>

      <Section title="Chips" caption="Color cue + text label both present (a11y).">
        <div className="flex flex-col gap-4">
          <div className="flex flex-wrap gap-2">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">Status:</span>
            <StatusChip status="ACTIVE" />
            <StatusChip status="TRIAL" />
            <StatusChip status="INVITED" />
            <StatusChip status="SUSPENDED" />
            <StatusChip status="TERMINATED" />
            <StatusChip status="ARCHIVED" />
            <StatusChip status="ONBOARDING" />
            <StatusChip status="INACTIVE" />
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">Tier:</span>
            <TierChip tier="ENTERPRISE" />
            <TierChip tier="MID_MARKET" />
            <TierChip tier="SMB" />
            <TierChip tier="SINGLE_STORE" />
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">Result:</span>
            <ResultChip result="SUCCESS" />
            <ResultChip result="PENDING" />
            <ResultChip result="DENIED" />
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">Action:</span>
            <ActionChip action="VIEW" />
            <ActionChip action="CONFIGURE" />
            <ActionChip action="EXECUTE" />
            <ActionChip action="APPROVE" />
            <ActionChip action="OVERRIDE" />
            <ActionChip action="AUDIT" />
          </div>
          <div className="flex flex-wrap gap-2">
            <span className="text-xs uppercase tracking-wider text-muted-foreground">Scope:</span>
            <ScopeChip scope="GLOBAL" />
            <ScopeChip scope="TENANT" />
            <ScopeChip scope="STORE" />
          </div>
        </div>
      </Section>

      <Section title="Modal / Drawer / ConfirmDialog">
        <div className="flex flex-wrap gap-3">
          <Button variant="outline" onClick={() => setModalOpen(true)}>Open Modal</Button>
          <Button variant="outline" onClick={() => setDrawerOpen(true)}>Open Drawer</Button>
          <Button variant="outline" onClick={() => setConfirmOpen(true)}>
            Open ConfirmDialog (default)
          </Button>
          <Button variant="destructive" onClick={() => setDestructiveOpen(true)}>
            Open ConfirmDialog (destructive)
          </Button>
          <Button variant="destructive" onClick={() => setTypeConfirmOpen(true)}>
            Open ConfirmDestructive (type-to-confirm)
          </Button>
        </div>

        <Modal
          open={modalOpen}
          onOpenChange={setModalOpen}
          title="Provision tenant"
          subtitle="v0 just renders the modal. Submit toasts &quot;v1&quot;."
          footer={
            <>
              <Button variant="outline" onClick={() => setModalOpen(false)}>Cancel</Button>
              <Button onClick={() => { comingInV1("Provision tenant"); setModalOpen(false); }}>
                Provision
              </Button>
            </>
          }
        >
          <p className="text-muted-foreground">Form fields would render here.</p>
        </Modal>

        <Drawer
          open={drawerOpen}
          onOpenChange={setDrawerOpen}
          title="Buc-ee&apos;s"
          subtitle="Convenience / Fuel · USA"
          footer={
            <>
              <Button variant="outline" onClick={() => comingInV1("Edit tenant")}>Edit</Button>
              <Button variant="destructive" onClick={() => comingInV1("Suspend tenant")}>
                Suspend
              </Button>
            </>
          }
        >
          <div className="flex flex-col gap-4">
            <div>
              <p className="text-xs uppercase tracking-wider text-muted-foreground">Modules</p>
              <div className="mt-2 flex flex-wrap gap-2">
                <StatusChip status="ACTIVE" />
                <TierChip tier="ENTERPRISE" />
              </div>
            </div>
            <p className="text-muted-foreground">More detail content...</p>
          </div>
        </Drawer>

        <ConfirmDialog
          open={confirmOpen}
          onOpenChange={setConfirmOpen}
          title="Confirm action"
          body="This is a non-destructive confirmation. v0 default variant."
          onConfirm={() => comingInV1("Confirm")}
        />

        <ConfirmDialog
          open={destructiveOpen}
          onOpenChange={setDestructiveOpen}
          title="Suspend tenant?"
          body="The tenant will lose access immediately. This action can be reversed by an admin."
          variant="destructive"
          confirmLabel="Suspend"
          onConfirm={() => comingInV1("Suspend tenant")}
        />

        <ConfirmDestructive
          open={typeConfirmOpen}
          onOpenChange={setTypeConfirmOpen}
          title="Delete this resource"
          description={
            <>
              This action cannot be undone. Type <code>DELETE</code> to confirm.
            </>
          }
          confirmText="DELETE"
          confirmLabel="Delete"
          onConfirm={async () => {
            await new Promise((r) => setTimeout(r, 600));
            toast.success("Resource deleted (demo)");
          }}
        />
      </Section>
    </div>
  );
}
