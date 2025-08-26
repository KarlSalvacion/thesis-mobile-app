import React from 'react'
import { View, Text } from 'react-native'

const Mapscreen = () => {
  return (
    <View className=" h-full w-full justify-center items-center bg-bgColor1">
      
      { /* Placeholder for Map */ }
      <View className='h-[310px] w-[380px] bg-greenColor item-center justify-center rounded-lg'>
        <Text className='text-center'>SAMPLE MAP</Text>
      </View>

      <View className='h-[50px] w-[380px] bg-transparent mt-2 p-0 flex-row items-center justify-between' >
        {
        /* Legend */
        }
        <View className='flex-row justify-between items-center g-[5px]'>
          <View className='bg-green-700 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Low</Text>
        </View>

        <View className='flex-row justify-between items-center g-[5px]'>
          <View className='bg-yellow-100 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Medium</Text>
        </View>

        <View className='flex-row justify-between items-center g-[5px]'>
          <View className='bg-red-600 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>High</Text>
        </View>
        <View className='flex-row justify-between items-center g-[5px]'>
          <View className='bg-blue-700 h-[14px] w-[18px] rounded-md'/>
          <Text className='text-s ml-2 font-medium text-gray-700'>Flight Path</Text>
        </View>

      </View>
      
      <View className='flex-col justify-between items-left mt-4 bg-pink-100 h-[120px] w-[380px] rounded-lg p-4'>
        <Text className='text-left text-gray-700 mt-2'>Density Overview</Text>
        <View className='flex-row w-full justify-between  mt-1'>
          <View className='flex-col justify-center items-center mx-2 bg-gray-200 w-24'>
            <Text>High</Text>
            <Text>Sample</Text>
          </View>

          <View className='flex-col justify-center items-center mx-2 border-l-2 border-r-2 border-gray-300 px-4 w-24'>
            <Text>High</Text>
            <Text>Sample</Text>
          </View>

          <View className='flex-col justify-center items-center mx-2 w-24'>
            <Text>High</Text>
            <Text>Sample</Text>
          </View>
        </View>
      </View>

    </View> 
  )
}

export default Mapscreen