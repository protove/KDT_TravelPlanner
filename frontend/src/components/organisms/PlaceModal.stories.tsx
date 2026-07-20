import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "@/components/atoms/Button";
import { PlaceModal, type PlaceDateChip } from "./PlaceModal";

const meta = {
  title: "Organisms/PlaceModal",
  component: PlaceModal,
  tags: ["autodocs"],
} satisfies Meta<typeof PlaceModal>;

export default meta;
type Story = StoryObj<typeof meta>;

function EditDemo() {
  const [open, setOpen] = React.useState(false);
  const [note, setNote] = React.useState("도착 후 리무진버스로 이동");
  const [chips, setChips] = React.useState<PlaceDateChip[]>([
    { label: "07.12", selected: true },
    { label: "07.13", selected: false },
    { label: "07.14", selected: false },
  ]);

  return (
    <>
      <Button onClick={() => setOpen(true)}>장소 수정</Button>
      <PlaceModal
        open={open}
        onOpenChange={setOpen}
        mode="edit"
        title="나리타 국제공항"
        name=""
        onNameChange={() => {}}
        note={note}
        onNoteChange={setNote}
        dateChips={chips}
        onSelectDateChip={(i) => setChips((prev) => prev.map((c, idx) => ({ ...c, selected: idx === i })))}
        onSave={() => setOpen(false)}
      />
    </>
  );
}

function AddDemo() {
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [note, setNote] = React.useState("");

  return (
    <>
      <Button onClick={() => setOpen(true)}>+ 목적지 추가</Button>
      <PlaceModal
        open={open}
        onOpenChange={setOpen}
        mode="add"
        title="목적지 추가"
        name={name}
        onNameChange={setName}
        note={note}
        onNoteChange={setNote}
        onSave={() => setOpen(false)}
      />
    </>
  );
}

const noopArgs = {
  open: false,
  onOpenChange: () => {},
  mode: "add" as const,
  title: "",
  name: "",
  onNameChange: () => {},
  note: "",
  onNoteChange: () => {},
  onSave: () => {},
};

export const EditPlace: Story = { args: noopArgs, render: () => <EditDemo /> };
export const AddPlace: Story = { args: noopArgs, render: () => <AddDemo /> };
