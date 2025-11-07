import React from 'react';
import { StyleSheet } from 'react-native';
import { GestureDetector, Gesture, GestureHandlerRootView } from 'react-native-gesture-handler';
import Animated, {
  useAnimatedStyle,
  useSharedValue,
  withTiming,
} from 'react-native-reanimated';

interface ZoomableImageProps {
  uri: string;
  style?: any;
  resizeMode?: 'contain' | 'cover' | 'stretch' | 'center';
}

export default function ZoomableImage({ uri, style, resizeMode = 'contain' }: ZoomableImageProps) {
  const scale = useSharedValue(1);
  const savedScale = useSharedValue(1);
  const translateX = useSharedValue(0);
  const translateY = useSharedValue(0);
  const savedTranslateX = useSharedValue(0);
  const savedTranslateY = useSharedValue(0);

  const pinchGesture = Gesture.Pinch()
    .onUpdate((e) => {
      let newScale = savedScale.value * e.scale;
      // Clamp scale between 1 and 3
      if (newScale < 1) newScale = 1;
      if (newScale > 3) newScale = 3;
      scale.value = newScale;
    })
    .onEnd(() => {
      // Only reset if below min zoom
      if (scale.value < 1) {
        scale.value = withTiming(1, { duration: 200 });
        translateX.value = withTiming(0, { duration: 200 });
        translateY.value = withTiming(0, { duration: 200 });
        savedTranslateX.value = 0;
        savedTranslateY.value = 0;
      }
      // Otherwise, just clamp and stay at max
      savedScale.value = scale.value;
    });

  const panGesture = Gesture.Pan()
    .onUpdate((e) => {
      // Always allow panning
      let nextX = savedTranslateX.value + e.translationX;
      let nextY = savedTranslateY.value + e.translationY;
      // Clamp so image never goes out of view
      const maxOffset = (scale.value - 1) * 0.5 * 300; // 300 is approx image size, adjust as needed
      if (nextX > maxOffset) nextX = maxOffset;
      if (nextX < -maxOffset) nextX = -maxOffset;
      if (nextY > maxOffset) nextY = maxOffset;
      if (nextY < -maxOffset) nextY = -maxOffset;
      translateX.value = nextX;
      translateY.value = nextY;
    })
    .onEnd(() => {
      savedTranslateX.value = translateX.value;
      savedTranslateY.value = translateY.value;
    });

  const composed = Gesture.Simultaneous(
    pinchGesture,
    panGesture
  );

  const animatedStyle = useAnimatedStyle(() => ({
    transform: [
      { translateX: translateX.value },
      { translateY: translateY.value },
      { scale: scale.value },
    ],
  }));

  return (
    <GestureHandlerRootView style={[styles.root, style]}>
      <GestureDetector gesture={composed}>
        <Animated.View style={styles.container}>
          <Animated.Image
            source={{ uri }}
            style={[styles.image, animatedStyle]}
            resizeMode={resizeMode}
          />
        </Animated.View>
      </GestureDetector>
    </GestureHandlerRootView>
  );
}

const styles = StyleSheet.create({
  root: {
    width: '100%',
    height: '100%',
  },
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
  },
  image: {
    width: '100%',
    height: '100%',
  },
});
