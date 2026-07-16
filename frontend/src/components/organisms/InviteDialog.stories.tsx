import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "@/components/atoms/Button";
import { InviteDialog, type InviteCandidate } from "./InviteDialog";

const meta = {
  title: "Organisms/InviteDialog",
  component: InviteDialog,
  tags: ["autodocs"],
} satisfies Meta<typeof InviteDialog>;

export default meta;
type Story = StoryObj<typeof meta>;

function Demo() {
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  const [results, setResults] = React.useState<InviteCandidate[]>([
    { id: "1", name: "박유진", avatarColor: "#0ea5e9", permission: "read" },
    { id: "2", name: "이하늘", avatarColor: "#9747ff", permission: "write" },
  ]);

  return (
    <>
      <Button onClick={() => setOpen(true)}>참여자 초대</Button>
      <InviteDialog
        open={open}
        onOpenChange={setOpen}
        query={query}
        onQueryChange={setQuery}
        results={results}
        onPermissionChange={(id, permission) =>
          setResults((prev) => prev.map((r) => (r.id === id ? { ...r, permission } : r)))
        }
        onInvite={() => {}}
      />
    </>
  );
}

const noopArgs = {
  open: false,
  onOpenChange: () => {},
  query: "",
  onQueryChange: () => {},
  results: [],
  onPermissionChange: () => {},
  onInvite: () => {},
};

export const Default: Story = { args: noopArgs, render: () => <Demo /> };
