package org.pulseaudiolambda

import android.app.MediaProjection
import android.content.Context
import android.media.*
import android.os.Build
import kotlinx.coroutines.*
import org.pytorch.IValue
import org.pytorch.Module
import org.pytorch.Tensor

/**
 * Captures system audio, runs the stem separation model and mixes
 * stems according to user-selected volumes.
 */
class StemService(private val context: Context) {
    private val scope = CoroutineScope(Dispatchers.Default)
    private val volumes = mutableMapOf(
        Stem.DRUMS to 1f,
        Stem.GUITAR to 1f,
        Stem.VOCALS to 1f,
        Stem.OTHER to 1f,
    )

    private var module: Module? = null
    private var job: Job? = null

    /** Start capturing and processing audio. */
    fun start(mediaProjection: MediaProjection? = null) {
        module = Module.load(assetFilePath("separation.pt"))
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            // mediaProjection must be obtained by prompting the user via MediaProjectionManager.
            if (mediaProjection == null) return
            val config = AudioPlaybackCaptureConfiguration.Builder(mediaProjection)
                .addMatchingUsage(AudioAttributes.USAGE_MEDIA)
                .build()

            val record = AudioRecord.Builder()
                .setAudioPlaybackCaptureConfig(config)
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(44100)
                        .setChannelMask(AudioFormat.CHANNEL_IN_STEREO)
                        .build()
                )
                .build()

            val track = AudioTrack.Builder()
                .setAudioFormat(record.format)
                .setBufferSizeInBytes(record.bufferSizeInFrames)
                .build()

            job = scope.launch {
                val buffer = ShortArray(2048)
                record.startRecording()
                track.play()
                while (isActive) {
                    val read = record.read(buffer, 0, buffer.size)
                    if (read > 0) {
                        val out = process(buffer, read)
                        track.write(out, 0, out.size)
                    }
                }
                record.stop()
                track.stop()
            }
        }
    }

    fun stop() { job?.cancel() }

    fun setVolume(stem: Stem, volume: Float) { volumes[stem] = volume }

    private fun process(samples: ShortArray, length: Int): ShortArray {
        val floats = FloatArray(length)
        for (i in 0 until length) floats[i] = samples[i] / 32768f
        val input = Tensor.fromBlob(floats, longArrayOf(1, length.toLong()))
        val outputs = module?.forward(IValue.from(input))?.toTensorList() ?: return samples
        val mix = FloatArray(length)
        val stems = Stem.values()
        for (i in outputs.indices) {
            val stemBuf = outputs[i].dataAsFloatArray
            val vol = volumes[stems[i]] ?: 1f
            for (j in 0 until length) {
                mix[j] += stemBuf[j] * vol
            }
        }
        val out = ShortArray(length)
        for (i in 0 until length) {
            val v = (mix[i] * 32768f).toInt().coerceIn(-32768, 32767)
            out[i] = v.toShort()
        }
        return out
    }

    private fun assetFilePath(assetName: String): String {
        val file = java.io.File(context.filesDir, assetName)
        if (file.exists() && file.length() > 0) return file.absolutePath
        context.assets.open(assetName).use { input ->
            java.io.FileOutputStream(file).use { output ->
                input.copyTo(output)
            }
        }
        return file.absolutePath
    }
}
