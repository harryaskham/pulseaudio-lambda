package org.pulseaudiolambda

import android.Manifest
import android.app.Activity
import android.content.Context
import android.content.Intent
import android.content.BroadcastReceiver
import android.content.IntentFilter
import android.content.pm.PackageManager
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Bundle
import android.widget.SeekBar
import android.widget.Button
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.core.app.ActivityCompat
import androidx.core.content.ContextCompat
import org.pulseaudiolambda.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity() {
    private lateinit var binding: ActivityMainBinding
    private var isRunning = false
    private var statusRegistered = false

    private val statusReceiver = object : BroadcastReceiver() {
        override fun onReceive(context: Context?, intent: Intent?) {
            if (intent?.action != StemService.ACTION_STATUS) return
            val state = intent.getStringExtra("state") ?: "IDLE"
            val modelLoaded = intent.getBooleanExtra("modelLoaded", false)
            val modelLoadMs = intent.getLongExtra("modelLoadMs", 0)
            val modelName = intent.getStringExtra("modelName") ?: "separation.pt"
            val modelBytes = intent.getLongExtra("modelBytes", 0)
            val processedFrames = intent.getLongExtra("processedFrames", 0)
            val lastInferenceMs = intent.getLongExtra("lastInferenceMs", 0)
            val error = intent.getStringExtra("error")

            val sampleRate = 44100.0
            val seconds = processedFrames / sampleRate
            val latencyText = if (lastInferenceMs > 0) String.format("%d ms/chunk", lastInferenceMs) else "-"
            val mb = if (modelBytes > 0) modelBytes.toDouble() / (1024.0 * 1024.0) else 0.0
            val modelText = if (modelLoaded)
                String.format("Model: %s (%.1f MB) loaded (%.0f ms)", modelName, mb, modelLoadMs.toDouble())
            else if (modelBytes > 0)
                String.format("Model: %s (%.1f MB) not loaded", modelName, mb)
            else
                "Model: not loaded"
            val statusText = if (!error.isNullOrBlank()) "Status: Error - $error" else "Status: $state"

            binding.status.text = statusText
            binding.model.text = modelText
            binding.processed.text = String.format("Processed: %.1f s", seconds)
            binding.latency.text = "Latency: $latencyText"

            val running = state == StemEngine.State.RUNNING.name
            isRunning = running
            binding.startStop.text = if (running) "Stop" else "Start"
            setSlidersEnabled(running)
        }
    }

    private val requestRecordAudio = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted -> if (granted) requestProjection() }

    private val requestProjectionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            startStemService(result.resultCode, result.data!!)
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        binding.startStop.text = "Start"
        binding.startStop.setOnClickListener {
            if (isRunning) {
                stopStemService()
            } else {
                requestStart()
            }
        }

        setupSlider(binding.drums, Stem.DRUMS)
        setupSlider(binding.bass, Stem.BASS)
        setupSlider(binding.vocals, Stem.VOCALS)
        setupSlider(binding.other, Stem.OTHER)
        setSlidersEnabled(false)
    }

    override fun onResume() {
        super.onResume()
        if (!statusRegistered) {
            val filter = IntentFilter(StemService.ACTION_STATUS)
            if (Build.VERSION.SDK_INT >= 33) {
                registerReceiver(statusReceiver, filter, Context.RECEIVER_NOT_EXPORTED)
            } else {
                @Suppress("DEPRECATION")
                registerReceiver(statusReceiver, filter)
            }
            statusRegistered = true
        }
    }

    override fun onPause() {
        if (statusRegistered) {
            unregisterReceiver(statusReceiver)
            statusRegistered = false
        }
        super.onPause()
    }

    private fun requestProjection() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            val mgr = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
            val intent = mgr.createScreenCaptureIntent()
            requestProjectionLauncher.launch(intent)
        }
    }

    private fun requestStart() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            requestRecordAudio.launch(Manifest.permission.RECORD_AUDIO)
        } else {
            requestProjection()
        }
    }

    private fun startStemService(resultCode: Int, data: android.content.Intent) {
        val intent = Intent(this, StemService::class.java).apply {
            action = StemService.ACTION_START
            putExtra(StemService.EXTRA_RESULT_CODE, resultCode)
            putExtra(StemService.EXTRA_RESULT_DATA, data)
        }
        ContextCompat.startForegroundService(this, intent)
    }

    private fun stopStemService() {
        val intent = Intent(this, StemService::class.java).apply { action = StemService.ACTION_STOP }
        startService(intent)
    }

    private fun sendVolume(stem: Stem, vol: Float) {
        val intent = Intent(this, StemService::class.java).apply {
            action = StemService.ACTION_SET_VOLUME
            putExtra(StemService.EXTRA_STEM, stem.name)
            putExtra(StemService.EXTRA_VOLUME, vol)
        }
        startService(intent)
    }

    private fun setupSlider(bar: SeekBar, stem: Stem) {
        bar.progress = 100
        bar.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(sb: SeekBar?, progress: Int, fromUser: Boolean) {
                sendVolume(stem, progress / 100f)
            }
            override fun onStartTrackingTouch(sb: SeekBar?) {}
            override fun onStopTrackingTouch(sb: SeekBar?) {}
        })
    }

    private fun setSlidersEnabled(enabled: Boolean) {
        binding.drums.isEnabled = enabled
        binding.bass.isEnabled = enabled
        binding.vocals.isEnabled = enabled
        binding.other.isEnabled = enabled
    }
}

enum class Stem { DRUMS, BASS, VOCALS, OTHER }
