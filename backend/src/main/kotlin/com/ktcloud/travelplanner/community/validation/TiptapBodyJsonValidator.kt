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

	fun validate(bodyJson: JsonNode) {
		validateNode(bodyJson)
	}

	private fun validateNode(node: JsonNode) {
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

		val content = node.get("content")
		if (content != null && content.isArray) {
			content.forEach(::validateNode)
		}
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
