import * as React from "react";
import type { Meta, StoryObj } from "@storybook/nextjs-vite";
import { Button } from "@/components/atoms/Button";
import { PlaceModal, type PlaceDateChip, type PlaceSearchResultOption, type TimelineCategoryOption } from "./PlaceModal";

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
  const [category, setCategory] = React.useState<TimelineCategoryOption>("교통");
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
        category={category}
        onCategoryChange={setCategory}
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
  const [category, setCategory] = React.useState<TimelineCategoryOption>("관광지");
  const [placeQuery, setPlaceQuery] = React.useState("");
  const placeResults: PlaceSearchResultOption[] = placeQuery
    ? [{ placeId: "mock-1", name: `${placeQuery} 검색 결과` }]
    : [];

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
        category={category}
        onCategoryChange={setCategory}
        placeQuery={placeQuery}
        onPlaceQueryChange={setPlaceQuery}
        placeResults={placeResults}
        onSelectPlaceResult={(result) => {
          setName(result.name);
          setPlaceQuery("");
        }}
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
  category: "관광지" as TimelineCategoryOption,
  onCategoryChange: () => {},
  onSave: () => {},
};

export const EditPlace: Story = { args: noopArgs, render: () => <EditDemo /> };
export const AddPlace: Story = { args: noopArgs, render: () => <AddDemo /> };

/** READ_ONLY 권한으로 조회할 때: 모든 입력이 비활성화되고 저장 버튼이 사라진다. */
export const ReadOnly: Story = {
  args: {
    ...noopArgs,
    open: true,
    mode: "edit",
    title: "나리타 국제공항",
    note: "도착 후 리무진버스로 이동",
    category: "교통" as TimelineCategoryOption,
    readOnly: true,
  },
};
