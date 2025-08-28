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
      
      <View className="flex-col mt-4 bg-white h-[150px] w-[380px] rounded-2xl p-4 shadow-custom border-2 border-gray-300">
        <View className="bg-greenColor shadow-custom mb-2 self-start w-fit px-4 py-2 rounded-3xl">
          <Text className="text-left text-white text-md font-bold">Density Overview</Text>
        </View>
        

        <View className="flex-row justify-between items-center mt-2 h-[70px] w-full">
          {/* Box 1 */}
          <View className="flex-1 flex-col justify-center items-center  mx-1 rounded-md py-2">
            <Text className='text- font-bold'>Low</Text>
            <Text className='text-base font-medium'>Sample</Text>
          </View>

          {/* Box 2 */}
          <View className="flex-1 flex-col justify-center items-center  mx-1 rounded-md py-2">
            <Text className='text- font-bold'>Medium</Text>
            <Text className='text-base font-medium'>Sample</Text>
          </View>

          {/* Box 3 */}
          <View className="flex-1 flex-col justify-center items-center  mx-1 rounded-md py-2">
            <Text className='text- font-bold'>High</Text>
            <Text className='text-base font-medium'>Sample</Text>
          </View>
        </View>
      </View>
    </View> 
  )
}

export default Mapscreen