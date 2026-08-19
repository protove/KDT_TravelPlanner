package com.ktcloud.travelplanner.community.validation

import com.fasterxml.jackson.databind.ObjectMapper
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.assertThrows

class TiptapBodyJsonValidatorTest {

	private val objectMapper = ObjectMapper()

	@Test
	fun `accepts a bodyJson using only whitelisted node types, marks and attrs`() {
		val bodyJson = objectMapper.readTree(
			"""
			{
			  "type": "doc",
			  "content": [
			    {
			      "type": "heading",
			      "attrs": { "level": 2, "textAlign": "center" },
			      "content": [
			        { "type": "text", "text": "제목", "marks": [{ "type": "bold" }] }
			      ]
			    },
			    {
			      "type": "paragraph",
			      "attrs": { "textAlign": "left" },
			      "content": [
			        { "type": "text", "text": "본문 ", "marks": [{ "type": "italic" }, { "type": "underline" }] },
			        { "type": "hardBreak" }
			      ]
			    },
			    {
			      "type": "bulletList",
			      "content": [
			        {
			          "type": "listItem",
			          "content": [
			            { "type": "paragraph", "content": [{ "type": "text", "text": "항목1" }] }
			          ]
			        }
			      ]
			    },
			    {
			      "type": "image",
			      "attrs": { "src": "https://example.com/a.png", "alt": "설명" }
			    }
			  ]
			}
			""".trimIndent(),
		)

		TiptapBodyJsonValidator.validate(bodyJson)
	}

	@Test
	fun `rejects a bodyJson containing a node type outside the whitelist`() {
		val bodyJson = objectMapper.readTree(
			"""
			{
			  "type": "doc",
			  "content": [
			    {
			      "type": "codeBlock",
			      "content": [{ "type": "text", "text": "console.log(1)" }]
			    }
			  ]
			}
			""".trimIndent(),
		)

		assertThrows<InvalidBodyJsonException> {
			TiptapBodyJsonValidator.validate(bodyJson)
		}
	}

	@Test
	fun `rejects a bodyJson containing a mark outside the whitelist`() {
		val bodyJson = objectMapper.readTree(
			"""
			{
			  "type": "doc",
			  "content": [
			    {
			      "type": "paragraph",
			      "content": [
			        { "type": "text", "text": "취소선", "marks": [{ "type": "strike" }] }
			      ]
			    }
			  ]
			}
			""".trimIndent(),
		)

		assertThrows<InvalidBodyJsonException> {
			TiptapBodyJsonValidator.validate(bodyJson)
		}
	}
}
