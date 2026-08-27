package com.ktcloud.travelplanner.global.dto

import com.fasterxml.jackson.core.JsonParser
import com.fasterxml.jackson.databind.BeanProperty
import com.fasterxml.jackson.databind.DeserializationContext
import com.fasterxml.jackson.databind.JavaType
import com.fasterxml.jackson.databind.JsonDeserializer
import com.fasterxml.jackson.databind.annotation.JsonDeserialize
import com.fasterxml.jackson.databind.deser.ContextualDeserializer

// user 도메인 전용이 아니라 PATCH 요청에서 "필드 생략"과 "값을 null로 명시"를 구분하기 위한
// 범용 유틸 — travel/timeline 등 다른 도메인에서도 재사용된다. MSA 분리 시 user(Identity)
// 패키지와 함께 옮겨지면 안 되므로 global에 둔다.
@JsonDeserialize(using = PatchFieldDeserializer::class)
sealed interface PatchField<out T> {
	data object Absent : PatchField<Nothing>

	data class Present<T>(
		val value: T?,
	) : PatchField<T>
}

class PatchFieldDeserializer(
	private val valueType: JavaType? = null,
) : JsonDeserializer<PatchField<*>>(), ContextualDeserializer {
	override fun deserialize(
		parser: JsonParser,
		context: DeserializationContext,
	): PatchField<*> = PatchField.Present(
		context.readValue<Any?>(parser, requireNotNull(valueType)),
	)

	override fun getNullValue(context: DeserializationContext): PatchField<*> =
		PatchField.Present<Any?>(null)

	override fun createContextual(
		context: DeserializationContext,
		property: BeanProperty?,
	): JsonDeserializer<*> {
		val patchFieldType = property?.type ?: requireNotNull(context.contextualType)
		return PatchFieldDeserializer(patchFieldType.containedTypeOrUnknown(0))
	}
}
