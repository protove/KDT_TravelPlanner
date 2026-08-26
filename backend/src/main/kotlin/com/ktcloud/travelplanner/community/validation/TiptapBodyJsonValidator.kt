package com.ktcloud.travelplanner.community.validation

import com.fasterxml.jackson.databind.JsonNode
import com.ktcloud.travelplanner.global.exception.DomainException
import com.ktcloud.travelplanner.global.exception.ErrorCode

/**
 * community-api-contract.md 6-1, 6-2절 화이트리스트를 기준으로 Tiptap bodyJson을 재귀적으로 검증한다.
 * doc/text는 ProseMirror 스키마상 항상 등장하는 구조 노드라 화이트리스트에 포함해 허용한다.
 */
object TiptapBodyJsonValidator {

	private val ALLOWED_NODE_TYPES =
		setOf("doc", "text", "paragraph", "heading", "bulletList", "listItem", "image", "hardBreak")
	private val ALLOWED_MARK_TYPES = setOf("bold", "italic", "underline")
	private val ALLOWED_TEXT_ALIGN_VALUES = setOf("left", "center", "right")
	private val ALLOWED_HEADING_LEVELS = setOf(1, 2, 3)

	// community-api-contract.md에는 본문 길이 제한이 명시되어 있지 않다 — 어뷰징 방지를 위해
	// 서버에서 새로 추가한 제약. text 노드의 글자 수만 합산한다(마크업 구조는 카운트에 안 들어감).
	const val MAX_TEXT_LENGTH = 10_000

	fun validate(bodyJson: JsonNode) {
		val totalTextLength = validateNode(bodyJson)
		if (totalTextLength > MAX_TEXT_LENGTH) {
			throw InvalidBodyJsonException("본문은 최대 ${MAX_TEXT_LENGTH}자까지 작성할 수 있습니다.")
		}
	}

	// 구조 검증과 같은 트리 순회 한 번으로 text 노드 글자 수까지 누적해서 반환한다.
	private fun validateNode(node: JsonNode): Int {
		val typeNode = node.get("type")
		if (typeNode == null || !typeNode.isTextual) {
			throw InvalidBodyJsonException("노드에 type이 없습니다.")
		}

		val type = typeNode.asText()
		if (type !in ALLOWED_NODE_TYPES) {
			throw InvalidBodyJsonException("허용되지 않은 노드 타입입니다: $type")
		}

		validateAttrs(type, node.get("attrs"))
		validateMarks(node.get("marks"))

		var textLength = if (type == "text") node.get("text")?.asText()?.length ?: 0 else 0

		val content = node.get("content")
		if (content != null && content.isArray) {
			content.forEach { textLength += validateNode(it) }
		}
		return textLength
	}

	private fun validateAttrs(type: String, attrs: JsonNode?) {
		if (attrs == null || attrs.isNull) return
		if (!attrs.isObject) throw InvalidBodyJsonException("'$type' 노드의 attrs 형식이 올바르지 않습니다.")

		val allowedKeys = when (type) {
			"paragraph" -> setOf("textAlign")
			"heading" -> setOf("level", "textAlign")
			"image" -> setOf("src", "alt")
			else -> emptySet()
		}

		attrs.fieldNames().forEach { key ->
			if (key !in allowedKeys) {
				throw InvalidBodyJsonException("'$type' 노드에 허용되지 않은 속성입니다: $key")
			}
		}

		if ("textAlign" in allowedKeys) {
			val textAlign = attrs.get("textAlign")
			if (textAlign != null && !textAlign.isNull && textAlign.asText() !in ALLOWED_TEXT_ALIGN_VALUES) {
				throw InvalidBodyJsonException("textAlign 값이 올바르지 않습니다: ${textAlign.asText()}")
			}
		}

		if (type == "heading") {
			val level = attrs.get("level")
			if (level == null || !level.isIntegralNumber || level.asInt() !in ALLOWED_HEADING_LEVELS) {
				throw InvalidBodyJsonException("heading level은 1~3이어야 합니다.")
			}
		}
	}

	private fun validateMarks(marks: JsonNode?) {
		if (marks == null || marks.isNull) return
		if (!marks.isArray) throw InvalidBodyJsonException("marks 형식이 올바르지 않습니다.")

		marks.forEach { mark ->
			val typeNode = mark.get("type")
			if (typeNode == null || !typeNode.isTextual) {
				throw InvalidBodyJsonException("mark에 type이 없습니다.")
			}

			val markType = typeNode.asText()
			if (markType !in ALLOWED_MARK_TYPES) {
				throw InvalidBodyJsonException("허용되지 않은 mark입니다: $markType")
			}

			val markAttrs = mark.get("attrs")
			if (markAttrs != null && markAttrs.isObject && markAttrs.fieldNames().hasNext()) {
				throw InvalidBodyJsonException("'$markType' mark는 속성을 가질 수 없습니다.")
			}
		}
	}
}

class InvalidBodyJsonException(message: String) : DomainException(ErrorCode.VALIDATION_ERROR, message)
