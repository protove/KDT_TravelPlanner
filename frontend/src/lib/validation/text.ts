export const TITLE_MAX_LENGTH = 50;

// 장소 이름/음식 종류는 백엔드 TimelineItem.kt의 NAME_MAX_LENGTH/FOOD_SUBCATEGORY_MAX_LENGTH와 동일하게 맞춘다.
export const PLACE_NAME_MAX_LENGTH = 100;
export const FOOD_SUBCATEGORY_MAX_LENGTH = 30;
// 메모(할 일)는 백엔드에 길이 제한이 없어(TEXT 컬럼) 프론트 UX 기준으로만 정한 값.
export const PLACE_NOTE_MAX_LENGTH = 200;
// 여행 설명(소개)도 백엔드에 길이 제한이 없어 프론트 UX 기준으로만 정한 값.
export const DESCRIPTION_MAX_LENGTH = 500;
// 커뮤니티 댓글은 백엔드 CommentCreateRequest.kt의 @Size(max = 1000)과 동일하게 맞춘다.
export const COMMENT_MAX_LENGTH = 1000;
// 커뮤니티 게시글 본문(Tiptap)은 백엔드 TiptapBodyJsonValidator.MAX_TEXT_LENGTH와 동일하게 맞춘다.
export const BODY_MAX_LENGTH = 10_000;

// 같은 문자(기호·영문·숫자·한글 문단 전부 포함)가 5회 이상 연속되면 도배로 간주한다.
// "!!!!!", "-----", "ㄱㄱㄱㄱㄱ" 처럼 종류를 가리지 않고 반복 자체를 잡아낸다.
const REPEATED_CHAR_PATTERN = /(.)\1{4,}/u;

/** 같은 문자가 5회 이상 연속되는 도배성 입력인지 검사한다. */
export function hasRepeatedCharSpam(value: string): boolean {
  return REPEATED_CHAR_PATTERN.test(value);
}

// 완성된 한글 음절(가~힣)과 자모 낱자(ㄱ~ㅎ, ㅏ~ㅣ)는 유니코드 영역이 다르다.
// 이 정규식은 "자음/모음만 있고 글자로 합쳐지지 않은" 낱자가 하나라도 섞여 있으면 매치된다
// (예: "ㅈㄱㄴㅇㄹ", "ㄱㄱㄱㄱㄱ" 같은 키보드 난타 패턴).
const INCOMPLETE_HANGUL_PATTERN = /[ㄱ-ㅎㅏ-ㅣ]/;

/** 자음/모음만 있고 완성되지 않은 한글이 포함돼 있는지 검사한다. */
export function hasIncompleteHangul(value: string): boolean {
  return INCOMPLETE_HANGUL_PATTERN.test(value);
}

// 닉네임은 한글 완성형/영문/숫자만 허용한다 — 공백과 특수문자(자모 낱자 포함)는 전부 금지.
const NICKNAME_ALLOWED_PATTERN = /^[가-힣a-zA-Z0-9]+$/;

/** 닉네임 형식(공백·특수문자·낱자 금지)이 올바른지 검사한다. 빈 문자열은 false. */
export function isValidNicknameFormat(value: string): boolean {
  return NICKNAME_ALLOWED_PATTERN.test(value);
}

/**
 * 닉네임 형식을 검사하고, 문제가 있으면 이유별로 구체적인 에러 메시지를 돌려준다.
 * 문제가 없으면 undefined.
 */
export function getNicknameFormatError(value: string): string | undefined {
  if (/\s/.test(value)) return "닉네임에는 공백을 사용할 수 없어요.";
  if (hasIncompleteHangul(value)) return "완성되지 않은 한글(자음/모음)은 사용할 수 없어요.";
  if (!isValidNicknameFormat(value)) return "닉네임은 한글, 영문, 숫자만 사용할 수 있어요.";
  return undefined;
}
