import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "@/components/atoms/Button";
import { ParticipantManageDialog, type Participant } from "./ParticipantManageDialog";

const meta = {
  title: "Organisms/ParticipantManageDialog",
  component: ParticipantManageDialog,
  tags: ["autodocs"],
} satisfies Meta<typeof ParticipantManageDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

function Demo() {
  const [open, setOpen] = React.useState(false);
  const [participants, setParticipants] = React.useState<Participant[]>([
    { id: "1", name: "김지민", avatarColor: "#3b82f6", permission: "write", status: "accepted" },
    { id: "2", name: "박유진", avatarColor: "#0ea5e9", permission: "read", status: "accepted" },
    { id: "3", name: "이하늘", avatarColor: "#9747ff", permission: "read", status: "pending" },
  ]);

  return (
    <>
      <Button variant="outline" onClick={() => setOpen(true)}>
        참여자 관리
      </Button>
      <ParticipantManageDialog
        open={open}
        onOpenChange={setOpen}
        participants={participants}
        onPermissionChange={(id, permission) =>
          setParticipants((prev) => prev.map((p) => (p.id === id ? { ...p, permission } : p)))
        }
        onRemove={(id) => setParticipants((prev) => prev.filter((p) => p.id !== id))}
      />
    </>
  );
}

const noopArgs = {
  open: false,
  onOpenChange: () => {},
  participants: [],
  onPermissionChange: () => {},
  onRemove: () => {},
};

export const Default: Story = { args: noopArgs, render: () => <Demo /> };
