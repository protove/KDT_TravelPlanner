package com.ktcloud.travelplanner.monitoring.metrics

import org.junit.jupiter.api.Assertions.assertFalse
import org.junit.jupiter.api.Assertions.assertNotEquals
import org.junit.jupiter.api.Assertions.assertTrue
import org.junit.jupiter.api.Test
import org.junit.jupiter.api.io.TempDir
import java.nio.file.Files
import java.nio.file.Path
import java.util.concurrent.TimeUnit

class DevEntrypointTest {

	@Test
	fun `dev entrypoint checks health on the configured management port`() {
		val script = Files.readString(ENTRYPOINT_PATH)

		assertTrue(script.contains("""management_port="${'$'}{MANAGEMENT_SERVER_PORT:-9091}""""))
		assertTrue(script.contains("""http://127.0.0.1:${'$'}{management_port}/actuator/health"""))
		assertFalse(script.contains("http://127.0.0.1:8080/actuator/health"))
	}

	@Test
	fun `dev entrypoint fails when boot run exits before management health is ready`(
		@TempDir temporaryDirectory: Path,
	) {
		val entrypoint = temporaryDirectory.resolve("dev-entrypoint.sh")
		val gradleWrapper = temporaryDirectory.resolve("gradlew")
		val fakeBinDirectory = Files.createDirectory(temporaryDirectory.resolve("bin"))
		val fakeWget = fakeBinDirectory.resolve("wget")

		Files.copy(ENTRYPOINT_PATH, entrypoint)
		writeExecutable(
			gradleWrapper,
			"""
			#!/bin/sh
			exit 0
			""".trimIndent(),
		)
		writeExecutable(
			fakeWget,
			"""
			#!/bin/sh
			exit 1
			""".trimIndent(),
		)

		val process = ProcessBuilder("sh", entrypoint.fileName.toString())
			.directory(temporaryDirectory.toFile())
			.redirectErrorStream(true)
			.apply {
				environment()["PATH"] = "$fakeBinDirectory:${environment()["PATH"]}"
			}
			.start()

		assertTrue(process.waitFor(10, TimeUnit.SECONDS), "entrypoint did not terminate")
		val output = process.inputStream.bufferedReader().use { it.readText() }

		assertNotEquals(0, process.exitValue(), output)
		assertTrue(
			output.contains("Backend bootRun exited before management health became ready."),
			output,
		)
	}

	private fun writeExecutable(
		path: Path,
		content: String,
	) {
		Files.writeString(path, content)
		assertTrue(path.toFile().setExecutable(true))
	}

	private companion object {
		private val ENTRYPOINT_PATH: Path = Path.of("docker/dev-entrypoint.sh")
	}
}
