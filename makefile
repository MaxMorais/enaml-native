ARCH=armeabi-v7a
SDK_DIR=/home/jrm/Android/Sdk
NDK_DIR=/home/jrm/Android/Crystax/crystax-ndk-10.3.2/

clean-python:
	cd python-for-android/ && python p4a.py clean_dists
	cd python-for-android/ && python p4a.py clean_builds

build-python:
	cd python-for-android/ && python p4a.py apk --arch=$(ARCH) --private=../src --package=org.example.enamlnative --name="Enaml Native Application" --dist-name="enaml-native" --version=0.1 --requirements=python2crystax,pyjnius,atom,ply,enaml --android-api=25 --bootstrap=enaml --sdk-dir=$(SDK_DIR) --ndk-dir=$(NDK_DIR) --ndk-platform=21 --copy-libs
	cp -R ~/.local/share/python-for-android/dists/enaml-native/libs/$(ARCH) android/app/src/main/libs
	cp -R ~/.local/share/python-for-android/dists/enaml-native/python/$(ARCH) android/app/src/main/python/
	
run-android:
	adb install -r EnamlNativeApplication-0.1-debug.apk
	adb shell am start -n org.example.enamlnative/org.kivy.android.PythonActivity
	adb logcat
