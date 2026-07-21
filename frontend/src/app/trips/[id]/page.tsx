"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { Pencil, Trash2 } from "lucide-react";
import { Button } from "@/components/atoms/Button";
import { Input } from "@/components/atoms/Input";
import { Textarea } from "@/components/atoms/Textarea";
import { Icon } from "@/components/atoms/Icon";
import { Avatar, AvatarFallback } from "@/components/atoms/Avatar";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/atoms/Select";
import { AppHeader } from "@/components/organisms/AppHeader";
import { CalendarPopover } from "@/components/organisms/CalendarPopover";
import { MapPanel } from "@/components/organisms/MapPanel";
import { ScheduleBoard } from "@/components/organisms/ScheduleBoard";
import { PlaceModal, type PlaceDateChip } from "@/components/organisms/PlaceModal";
import { InviteDialog, type InviteCandidate } from "@/components/organisms/InviteDialog";
import { ParticipantManageDialog, type Participant } from "@/components/organisms/ParticipantManageDialog";
import { DateRangeBadge } from "@/components/molecules/DateRangeBadge";
import { PurposeTagSelect } from "@/components/molecules/PurposeTagSelect";
import { ConfirmDialog } from "@/components/molecules/ConfirmDialog";
import { CommentRow } from "@/components/molecules/CommentRow";
import { CommentInput } from "@/components/molecules/CommentInput";
import { DetailLayout } from "@/components/templates/DetailLayout";
import { useAuthStore } from "@/lib/stores/useAuthStore";
import { useTripStore } from "@/lib/stores/useTripStore";
import {
  useTripDetailStore,
  COMPANION_OPTIONS,
  PURPOSE_OPTIONS,
  type Place,
} from "@/lib/stores/useTripDetailStore";

const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

function getDateTabs(start: Date, end: Date) {
  const tabs: { key: string; label: string; date: Date }[] = [];
  const cur = new Date(start);
  while (cur <= end) {
    tabs.push({
      key: String(tabs.length),
      label: `${cur.getMonth() + 1}/${cur.getDate()} (${WEEKDAYS[cur.getDay()]})`,
      date: new Date(cur),
    });
    cur.setDate(cur.getDate() + 1);
  }
  return tabs;
}

export default function TripDetailPage() {
  const router = useRouter();
  const isLoggedIn = useAuthStore((s) => s.isLoggedIn);
  const user = useAuthStore((s) => s.user);

  const trips = useTripStore((s) => s.trips);
  const removeTrip = useTripStore((s) => s.removeTrip);

  const info = useTripDetailStore((s) => s.info);
  const members = useTripDetailStore((s) => s.members);
  const places = useTripDetailStore((s) => s.places);
  const comments = useTripDetailStore((s) => s.comments);
  const setCountry = useTripDetailStore((s) => s.setCountry);
  const setCity = useTripDetailStore((s) => s.setCity);
  const setCompanion = useTripDetailStore((s) => s.setCompanion);
  const setDescription = useTripDetailStore((s) => s.setDescription);
  const setDateRange = useTripDetailStore((s) => s.setDateRange);
  const togglePurpose = useTripDetailStore((s) => s.togglePurpose);
  const addPlace = useTripDetailStore((s) => s.addPlace);
  const updatePlace = useTripDetailStore((s) => s.updatePlace);
  const removePlace = useTripDetailStore((s) => s.removePlace);
  const addComment = useTripDetailStore((s) => s.addComment);

  // mock: 이 데모는 trip id와 무관하게 항상 같은 상세 데이터를 보여준다 (백엔드 연동 전).
  const isOwner = trips.find((t) => t.id === "1")?.mine ?? true;

  const [activeDay, setActiveDay] = React.useState("0");
  const [showCalendar, setShowCalendar] = React.useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = React.useState(false);
  const [showLeaveConfirm, setShowLeaveConfirm] = React.useState(false);
  const [showInvite, setShowInvite] = React.useState(false);
  const [showManage, setShowManage] = React.useState(false);
  const [commentDraft, setCommentDraft] = React.useState("");

  const [editingPlace, setEditingPlace] = React.useState<Place | null>(null);
  const [addingPlace, setAddingPlace] = React.useState(false);
  const [placeDraftName, setPlaceDraftName] = React.useState("");
  const [placeDraftNote, setPlaceDraftNote] = React.useState("");

  const [inviteQuery, setInviteQuery] = React.useState("");
  const [inviteResults, setInviteResults] = React.useState<InviteCandidate[]>([
    { id: "1", name: "이서민", avatarColor: "#f97316", permission: "read" },
    { id: "2", name: "박유진", avatarColor: "#0ea5e9", permission: "read" },
  ]);
  const [participants, setParticipants] = React.useState<Participant[]>([
    { id: "1", name: "박수아", avatarColor: "#6366f1", permission: "write", status: "accepted" },
    { id: "2", name: "이하늘", avatarColor: "#0ea5e9", permission: "read", status: "accepted" },
    { id: "3", name: "최준서", avatarColor: "#64748b", permission: "read", status: "pending" },
  ]);

  React.useEffect(() => {
    if (!isLoggedIn) router.replace("/landing");
  }, [isLoggedIn, router]);

  if (!isLoggedIn || !user) return null;

  const dateTabs = getDateTabs(info.dateRange.start, info.dateRange.end);
  const activeDayItems = places
    .filter((p) => p.day === Number(activeDay))
    .map((p) => ({ id: p.id, placeName: p.name, note: p.note || undefined }));
  const unassignedPlaces = places
    .filter((p) => p.day === null)
    .map((p) => ({ id: p.id, name: p.name }));
  const mapMarkers = places.map((p) => ({
    id: p.id,
    name: p.name,
    x: parseFloat(p.pos.left),
    y: parseFloat(p.pos.top),
  }));

  function openEditPlace(id: string) {
    const place = places.find((p) => p.id === id);
    if (!place) return;
    setEditingPlace(place);
    setPlaceDraftNote(place.note);
  }

  function openAddPlace() {
    setAddingPlace(true);
    setPlaceDraftName("");
    setPlaceDraftNote("");
  }

  function savePlaceModal() {
    if (editingPlace) {
      updatePlace(editingPlace.id, { note: placeDraftNote });
      setEditingPlace(null);
    } else if (addingPlace) {
      if (placeDraftName.trim()) {
        addPlace({ name: placeDraftName.trim(), note: placeDraftNote, day: null, pos: { top: "50%", left: "50%" } });
      }
      setAddingPlace(false);
    }
  }

  const dateChips: PlaceDateChip[] = dateTabs.map((tab) => ({
    label: `${tab.date.getMonth() + 1}.${tab.date.getDate()}`,
    selected: editingPlace?.day === Number(tab.key),
  }));

  return (
    <>
      <DetailLayout
      header={<AppHeader loggedIn userInitial={user.initial} avatarColor={user.avatarColor} onLogoClick={() => router.push("/trips")} />}
      detailHeader={
        <div className="flex flex-col gap-5">
          <button type="button" onClick={() => router.push("/trips")} className="text-sm font-bold text-primary">
            ← 여행일정 목록
          </button>

          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-2xl font-bold text-foreground">{info.title}</h1>
                {isOwner && (
                  <>
                    <button type="button" title="제목 · 기간 수정" className="text-muted-foreground">
                      <Icon icon={Pencil} size="sm" aria-label="제목 · 기간 수정" />
                    </button>
                    <button type="button" title="여행일정 삭제" className="text-destructive" onClick={() => setShowDeleteConfirm(true)}>
                      <Icon icon={Trash2} size="sm" aria-label="여행일정 삭제" />
                    </button>
                  </>
                )}
              </div>
              <div className="mt-1.5 flex">
                {members.map((m, i) => (
                  <Avatar key={i} className="h-[22px] w-[22px] ring-2 ring-background" style={i > 0 ? { marginLeft: "-6px" } : undefined}>
                    <AvatarFallback className="text-[10px] text-white" style={{ background: m.color }}>
                      {m.initial}
                    </AvatarFallback>
                  </Avatar>
                ))}
              </div>
            </div>

            {isOwner ? (
              <div className="flex items-center gap-2">
                <Button variant="outline" onClick={() => setShowInvite(true)}>
                  참여자 초대
                </Button>
                <Button onClick={() => setShowManage(true)}>참여자 관리</Button>
              </div>
            ) : (
              <Button variant="outline" onClick={() => setShowLeaveConfirm(true)}>
                나가기
              </Button>
            )}
          </div>

          <div className="relative flex w-fit flex-wrap items-center gap-1 rounded-full bg-card p-1.5 shadow-card">
            <div className="flex items-center gap-1.5 px-2.5 py-1.5">
              <span>📍</span>
              <Input
                value={info.country}
                onChange={(e) => setCountry(e.target.value)}
                placeholder="나라"
                className="h-auto w-[56px] border-none bg-transparent p-0.5 text-sm font-bold shadow-none"
              />
              <span className="text-border-strong">·</span>
              <Input
                value={info.city}
                onChange={(e) => setCity(e.target.value)}
                placeholder="도시"
                className="h-auto w-[64px] border-none bg-transparent p-0.5 text-sm font-bold shadow-none"
              />
            </div>
            <div className="h-5 w-px bg-border" />
            <button
              type="button"
              onClick={() => setShowCalendar((v) => !v)}
              className="flex items-center gap-2 rounded-full px-3.5 py-2 text-sm font-bold text-foreground hover:bg-muted"
            >
              📅 <DateRangeBadge start={info.dateRange.start} end={info.dateRange.end} />
            </button>
            <div className="h-5 w-px bg-border" />
            <Select value={info.companion} onValueChange={setCompanion}>
              <SelectTrigger className="h-auto w-auto gap-1.5 border-none px-3 py-1.5 shadow-none">
                <span>👥</span>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {COMPANION_OPTIONS.map((opt) => (
                  <SelectItem key={opt} value={opt}>
                    {opt}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>

            {showCalendar && (
              <div className="absolute left-0 top-[calc(100%+8px)] z-20">
                <CalendarPopover
                  value={info.dateRange}
                  onChange={(range) => setDateRange(range)}
                  onApply={() => setShowCalendar(false)}
                />
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-center gap-2">
            <span className="text-sm font-semibold text-muted-foreground">🏷 여행 목적</span>
            <PurposeTagSelect options={PURPOSE_OPTIONS} selected={info.purposes} onToggle={togglePurpose} />
          </div>
        </div>
      }
      schedule={
        <div className="flex flex-col gap-6">
          <ScheduleBoard
            days={dateTabs}
            activeDay={activeDay}
            onDayChange={setActiveDay}
            items={activeDayItems}
            unassigned={unassignedPlaces}
            onOpenItem={openEditPlace}
            onEditItem={openEditPlace}
            onCancelItem={(id) => updatePlace(id, { day: null })}
            onDeleteItem={removePlace}
            onAssignPlace={openEditPlace}
          />
          <Button variant="outline" className="w-full border-dashed" onClick={openAddPlace}>
            + 목적지 추가
          </Button>

          <div>
            <div className="mb-3 flex flex-col gap-3">
              {comments.map((c) => (
                <CommentRow key={c.id} name={c.name} avatarColor={c.avatarColor} timeLabel={c.timeLabel} text={c.text} />
              ))}
            </div>
            <CommentInput
              value={commentDraft}
              onChange={setCommentDraft}
              onSubmit={() => {
                addComment({ name: user.nickname, avatarColor: user.avatarColor, timeLabel: "방금 전", text: commentDraft });
                setCommentDraft("");
              }}
            />
          </div>

          <div>
            <div className="mb-2 text-sm font-bold text-foreground">여행 설명</div>
            <Textarea
              placeholder="이번 여행에 대해 간단히 소개해보세요"
              value={info.description}
              onChange={(e) => setDescription(e.target.value)}
              className="h-[90px]"
            />
          </div>
        </div>
      }
        map={<MapPanel markers={mapMarkers} onMarkerClick={openEditPlace} />}
      />

      <PlaceModal
        open={editingPlace != null || addingPlace}
        onOpenChange={(open) => {
          if (!open) {
            setEditingPlace(null);
            setAddingPlace(false);
          }
        }}
        mode={editingPlace ? "edit" : "add"}
        title={editingPlace ? editingPlace.name : "목적지 추가"}
        name={placeDraftName}
        onNameChange={setPlaceDraftName}
        note={placeDraftNote}
        onNoteChange={setPlaceDraftNote}
        dateChips={editingPlace ? dateChips : undefined}
        onSelectDateChip={(i) => editingPlace && updatePlace(editingPlace.id, { day: Number(dateTabs[i].key) })}
        onSave={savePlaceModal}
      />

      <InviteDialog
        open={showInvite}
        onOpenChange={setShowInvite}
        query={inviteQuery}
        onQueryChange={setInviteQuery}
        results={inviteResults}
        onPermissionChange={(id, permission) =>
          setInviteResults((prev) => prev.map((r) => (r.id === id ? { ...r, permission } : r)))
        }
        onInvite={() => {}}
      />

      <ParticipantManageDialog
        open={showManage}
        onOpenChange={setShowManage}
        participants={participants}
        onPermissionChange={(id, permission) =>
          setParticipants((prev) => prev.map((p) => (p.id === id ? { ...p, permission } : p)))
        }
        onRemove={(id) => setParticipants((prev) => prev.filter((p) => p.id !== id))}
      />

      <ConfirmDialog
        open={showDeleteConfirm}
        onOpenChange={setShowDeleteConfirm}
        title="여행일정 삭제"
        description="삭제하면 되돌릴 수 없습니다."
        confirmLabel="삭제하기"
        destructive
        onConfirm={() => {
          removeTrip("1");
          router.push("/trips");
        }}
      />

      <ConfirmDialog
        open={showLeaveConfirm}
        onOpenChange={setShowLeaveConfirm}
        title="일정을 나가시겠어요?"
        description="다시 참여하려면 초대를 받아야 해요."
        confirmLabel="나가기"
        onConfirm={() => router.push("/trips")}
      />
    </>
  );
}
